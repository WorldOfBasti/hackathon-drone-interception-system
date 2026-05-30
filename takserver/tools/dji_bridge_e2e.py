#!/usr/bin/env python3
"""
Hackathon E2E for the Android DJI TAK Bridge.

Builds the debug APK, sends one simulated app-format drone CoT event through
the TAK TCP listener, then verifies OpenTAKServer persisted it and exposes a
map point.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path
from xml.sax.saxutils import escape

from e2e_test import (
    E2EError,
    ROOT,
    log,
    verify_admin_login,
    verify_map_state_has_last_point,
    wait_cot_persisted,
    wait_http_health,
)


ANDROID_DIR_CANDIDATES = (
    ROOT / "android" / "dji-tak-bridge",
    ROOT.parent / "dji-stream-to-tak-bridge",
    ROOT.parent / "dji-tak-bridge",
)
UID = "DJI-MAVIC-AIR2-e2e"
CALLSIGN = "Mavic-Air-2-E2E"
APP_UID = "DJI-MAVIC-AIR2-mavic-air-2-e2e"
LAT = 48.137
LON = 11.575
ALT = 110.0
PACKAGE = "org.skysentinel.djitakbridge"
ACTIVITY = f"{PACKAGE}/.MainActivity"


def run(
    args: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> None:
    proc = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise E2EError(
            "Command failed: {}\nstdout:\n{}\nstderr:\n{}".format(
                " ".join(args),
                proc.stdout,
                proc.stderr,
            )
        )


def build_android_app() -> None:
    android_dir = resolve_android_dir()
    env = os.environ.copy()
    env.setdefault("ANDROID_HOME", str(Path.home() / "Library" / "Android" / "sdk"))
    log("building Android DJI TAK Bridge debug APK")
    run(["./gradlew", "assembleDebug"], cwd=android_dir, env=env, timeout=600)
    apk = android_dir / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if not apk.exists():
        raise E2EError(f"debug APK was not produced at {apk}")
    log(f"debug APK built: {apk}")


def resolve_android_dir() -> Path:
    for candidate in ANDROID_DIR_CANDIDATES:
        if (candidate / "gradlew").exists() and (candidate / "app" / "build.gradle.kts").exists():
            return candidate
    searched = ", ".join(str(candidate) for candidate in ANDROID_DIR_CANDIDATES)
    raise E2EError(f"Android project not found. Searched: {searched}")


def debug_apk_path() -> Path:
    android_dir = resolve_android_dir()
    return android_dir / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"


def run_adb(
    args: list[str],
    *,
    serial: str | None = None,
    timeout: int = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = ["adb"]
    if serial:
        command += ["-s", serial]
    command += args
    proc = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise E2EError(
            "ADB command failed: adb {}\nstdout:\n{}\nstderr:\n{}".format(
                " ".join(args),
                proc.stdout,
                proc.stderr,
            )
        )
    return proc


def adb_device_serial() -> str | None:
    if shutil.which("adb") is None:
        return None
    devices = run_adb(["devices"], timeout=15, check=False).stdout.splitlines()
    for line in devices[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            return parts[0]
    return None


def verify_app_launch(*, require_device: bool, android_host: str, android_port: int) -> str | None:
    serial = adb_device_serial()
    if not serial:
        if require_device:
            raise E2EError("no adb device connected for Android launch E2E")
        log("no adb device connected; skipping Android launch E2E")
        return None

    apk = debug_apk_path()
    if not apk.exists():
        raise E2EError(f"debug APK does not exist at {apk}")

    tak_host = android_host_for_device(serial, android_host, android_port)
    log(f"installing and launching Android app through adb on {serial}")
    run_adb(["install", "-r", str(apk)], serial=serial, timeout=180)
    grant_runtime_permissions(serial)
    run_adb(["logcat", "-c"], serial=serial, timeout=15)
    run_adb(["shell", "am", "force-stop", PACKAGE], serial=serial, timeout=15, check=False)
    run_adb(
        [
            "shell",
            "am",
            "start",
            "-W",
            "-n",
            ACTIVITY,
            "--ez",
            "autoStart",
            "true",
            "--ez",
            "simulator",
            "true",
            "--es",
            "takHost",
            tak_host,
            "--ei",
            "takPort",
            str(android_port),
            "--es",
            "callsign",
            CALLSIGN,
        ],
        serial=serial,
        timeout=30,
    )
    time.sleep(1)
    dismiss_android_compat_dialog(serial)
    time.sleep(5)

    pid = run_adb(["shell", "pidof", PACKAGE], serial=serial, timeout=15, check=False).stdout.strip()
    logs = run_adb(["logcat", "-d", "-t", "1200"], serial=serial, timeout=30, check=False).stdout
    crash_excerpt = app_crash_excerpt(logs)
    if crash_excerpt:
        raise E2EError(f"Android app crashed after launch:\n{crash_excerpt}")
    if not pid:
        raise E2EError("Android app process is not running after launch")
    log(f"Android app launch E2E passed with pid {pid}; streaming to {tak_host}:{android_port}")
    return APP_UID


def dismiss_android_compat_dialog(serial: str) -> None:
    dump = run_adb(
        ["exec-out", "uiautomator", "dump", "/dev/tty"],
        serial=serial,
        timeout=20,
        check=False,
    )
    xml = dump.stdout
    if "Android App Compatibility" not in xml:
        return

    import re

    ok_match = re.search(r'text="OK"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml)
    if not ok_match:
        log("Android compatibility dialog detected but OK button bounds were not found")
        return
    left, top, right, bottom = [int(value) for value in ok_match.groups()]
    x = (left + right) // 2
    y = (top + bottom) // 2
    log("dismissing Android 16 KB compatibility dialog")
    run_adb(["shell", "input", "tap", str(x), str(y)], serial=serial, timeout=15, check=False)


def android_host_for_device(serial: str, configured_host: str, port: int) -> str:
    if configured_host:
        return configured_host
    if serial.startswith("emulator-"):
        return "10.0.2.2"
    run_adb(["reverse", f"tcp:{port}", f"tcp:{port}"], serial=serial, timeout=15)
    return "127.0.0.1"


def grant_runtime_permissions(serial: str) -> None:
    permissions = (
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.ACCESS_COARSE_LOCATION",
        "android.permission.READ_PHONE_STATE",
        "android.permission.BLUETOOTH_CONNECT",
    )
    for permission in permissions:
        run_adb(["shell", "pm", "grant", PACKAGE, permission], serial=serial, timeout=15, check=False)


def app_crash_excerpt(logs: str) -> str:
    lines = logs.splitlines()
    markers = (
        f">>> {PACKAGE} <<<",
        f"Cmdline: {PACKAGE}",
        f"Process {PACKAGE} ",
        f"{PACKAGE}/.MainActivity",
    )
    crash_words = (
        "FATAL EXCEPTION",
        "AndroidRuntime",
        "SIGSEGV",
        "native_crash",
        "has died",
        "Fatal signal",
    )
    matching_indexes: list[int] = []
    for index, line in enumerate(lines):
        if any(marker in line for marker in markers) and any(word in line for word in crash_words):
            matching_indexes.append(index)
        if f"Process {PACKAGE}" in line and "has died" in line:
            matching_indexes.append(index)
    if not matching_indexes:
        return ""

    excerpts: list[str] = []
    seen: set[int] = set()
    for index in matching_indexes[:3]:
        start = max(index - 8, 0)
        end = min(index + 24, len(lines))
        for line_index in range(start, end):
            if line_index not in seen:
                excerpts.append(lines[line_index])
                seen.add(line_index)
    return "\n".join(excerpts)


def cot_xml() -> bytes:
    now = dt.datetime.now(dt.timezone.utc)
    stale = now + dt.timedelta(minutes=2)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_timestamp = stale.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return (
        f'<event version="2.0" uid="{escape(UID)}" type="a-f-A-M-F" how="m-g" '
        f'time="{timestamp}" start="{timestamp}" stale="{stale_timestamp}">'
        f'<point lat="{LAT}" lon="{LON}" hae="{ALT}" ce="5.0" le="5.0"/>'
        "<detail>"
        f'<contact callsign="{escape(CALLSIGN)}"/>'
        '<takv device="DJI Mavic Air 2" platform="Android" os="DJI TAK Bridge" version="0.1.0"/>'
        '<precisionlocation geopointsrc="simulator" altsrc="simulator"/>'
        '<track course="90.0" speed="8.0"/>'
        "<remarks>DJI TAK Bridge telemetry</remarks>"
        "</detail>"
        "</event>"
    ).encode()


def send_simulated_bridge_cot(host: str, port: int) -> None:
    payload = cot_xml()
    log(f"sending simulated Android bridge CoT to {host}:{port}")
    with socket.create_connection((host, port), timeout=8) as sock:
        time.sleep(0.5)
        sock.sendall(payload)
        time.sleep(2.0)
    log(f"sent bridge CoT {UID}")


def verify_map_state_has_any_last_point(uid: str, token: str) -> None:
    from e2e_test import http_get, wait_for

    def has_last_point():
        status, body = http_get(
            "/api/map_state",
            headers={"Accept": "application/json", "Authentication-Token": token},
        )
        if status != 200:
            return False
        euds = json.loads(body.decode()).get("euds", [])
        eud = next((entry for entry in euds if entry.get("uid") == uid), None)
        return bool(eud and eud.get("last_point"))

    wait_for(f"map state last_point for {uid}", has_last_point, timeout=45, interval=2)
    log(f"map state includes last_point for {uid}")


def main() -> None:
    parser = argparse.ArgumentParser(description="E2E test for Android DJI TAK Bridge")
    parser.add_argument("--no-build", action="store_true", help="Skip APK build")
    parser.add_argument(
        "--skip-launch-app",
        action="store_true",
        help="Skip adb install/launch crash check",
    )
    parser.add_argument(
        "--require-launch-app",
        action="store_true",
        help="Fail if no adb device is available for the launch check",
    )
    parser.add_argument(
        "--android-host",
        default="",
        help="TAK host passed into the Android app. Defaults to 10.0.2.2 for emulator, 192.0.2.10 for hardware.",
    )
    parser.add_argument(
        "--android-port",
        type=int,
        default=8088,
        help="TAK TCP port passed into the Android app",
    )
    parser.add_argument("--host", default="localhost", help="TAK TCP host")
    parser.add_argument("--port", type=int, default=8088, help="TAK TCP port")
    args = parser.parse_args()

    if not args.no_build:
        build_android_app()

    wait_http_health()
    token = verify_admin_login()

    app_uid = None
    try:
        if not args.skip_launch_app:
            app_uid = verify_app_launch(
                require_device=args.require_launch_app,
                android_host=args.android_host,
                android_port=args.android_port,
            )

        if app_uid:
            wait_cot_persisted(app_uid, timeout=45)
            verify_map_state_has_any_last_point(app_uid, token)
        else:
            send_simulated_bridge_cot(args.host, args.port)
            wait_cot_persisted(UID, timeout=45)
            verify_map_state_has_last_point(UID, token)
    finally:
        if not args.skip_launch_app:
            serial = adb_device_serial()
            if serial:
                run_adb(["shell", "am", "force-stop", PACKAGE], serial=serial, timeout=15, check=False)

    log("Android DJI TAK Bridge E2E passed")


if __name__ == "__main__":
    try:
        main()
    except E2EError as error:
        print(f"[dji-bridge-e2e] FAILED: {error}", flush=True)
        raise SystemExit(1)
