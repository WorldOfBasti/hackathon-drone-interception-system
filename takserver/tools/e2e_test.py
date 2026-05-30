#!/usr/bin/env python3
"""
End-to-end smoke test for the Docker TAK Server stack.

The test starts the compose stack, verifies the HTTP/Marti surfaces, sends
real CoT XML through both TCP and SSL TAK client listeners, then checks that
the CoT messages were persisted and are queryable through the Marti API.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "server" / "frontend"
UI_REPO = "https://github.com/brian7704/OpenTAKServer-UI.git"
UI_TAG = "v1.7.5"
UI_NODE_IMAGE = "node:22-bookworm"


class E2EError(RuntimeError):
    pass


def log(message: str) -> None:
    print(f"[e2e] {message}", flush=True)


def run(
    args: list[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if check and proc.returncode != 0:
        raise E2EError(
            "Command failed: {}\nstdout:\n{}\nstderr:\n{}".format(
                " ".join(args), proc.stdout, proc.stderr
            )
        )
    return proc


def run_bytes(args: list[str], *, timeout: int = 60) -> bytes:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise E2EError(
            "Command failed: {}\nstdout:\n{}\nstderr:\n{}".format(
                " ".join(args),
                proc.stdout.decode(errors="replace"),
                proc.stderr.decode(errors="replace"),
            )
        )
    return proc.stdout


def wait_for(label: str, check, *, timeout: int = 90, interval: float = 1.0):
    deadline = time.monotonic() + timeout
    last_error: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except Exception as exc:  # noqa: BLE001 - keep retry reason for diagnostics.
            last_error = exc
        time.sleep(interval)
    detail = f": {last_error}" if last_error else ""
    raise E2EError(f"Timed out waiting for {label}{detail}")


def prepare_frontend(tag: str) -> None:
    if (FRONTEND_DIR / "index.html").exists():
        log("frontend already present")
        return

    checkout = ROOT / ".docker" / "OpenTAKServer-UI"
    checkout.parent.mkdir(parents=True, exist_ok=True)

    if (checkout / ".git").exists():
        log(f"updating OpenTAKServer-UI {tag}")
        run(["git", "fetch", "--tags", "origin"], cwd=checkout, timeout=180)
        run(["git", "checkout", tag], cwd=checkout, timeout=60)
    else:
        log(f"cloning OpenTAKServer-UI {tag}")
        run(
            ["git", "clone", "--depth", "1", "--branch", tag, UI_REPO, str(checkout)],
            timeout=240,
        )

    use_host_node = host_node_can_build_ui()
    if use_host_node:
        log("installing UI dependencies with host npm")
        run(["npm", "install", "--legacy-peer-deps"], cwd=checkout, timeout=600)

        log("building UI with host npm")
        run(["npm", "run", "build"], cwd=checkout, timeout=600)
    else:
        log(f"building UI with {UI_NODE_IMAGE}")
        shutil.rmtree(checkout / "node_modules", ignore_errors=True)
        if (checkout / "node_modules").exists():
            run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{checkout}:/ui",
                    UI_NODE_IMAGE,
                    "rm",
                    "-rf",
                    "/ui/node_modules",
                ],
                timeout=120,
            )
        docker_user = []
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            docker_user = ["--user", f"{os.getuid()}:{os.getgid()}"]
        docker_base = [
            "docker",
            "run",
            "--rm",
            *docker_user,
            "-e",
            "NPM_CONFIG_CACHE=/tmp/.npm",
            "-v",
            f"{checkout}:/ui",
            "-w",
            "/ui",
            UI_NODE_IMAGE,
        ]
        run([*docker_base, "npm", "install", "--legacy-peer-deps"], timeout=900)
        run([*docker_base, "npm", "run", "build"], timeout=900)

    dist = checkout / "dist"
    if not (dist / "index.html").exists():
        raise E2EError(f"UI build did not produce {dist / 'index.html'}")

    if FRONTEND_DIR.exists():
        shutil.rmtree(FRONTEND_DIR)
    shutil.copytree(dist, FRONTEND_DIR)
    log(f"copied UI build to {FRONTEND_DIR}")


def host_node_can_build_ui() -> bool:
    if shutil.which("node") is None or shutil.which("npm") is None:
        return False
    proc = run(["node", "--version"], check=False, timeout=10)
    version = proc.stdout.strip().lstrip("v")
    try:
        major, minor, *_ = [int(part) for part in version.split(".")]
    except ValueError:
        return False
    if major > 22:
        return True
    if major == 22 and minor >= 12:
        return True
    if major == 20 and minor >= 19:
        return True
    return False


def compose(*args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return run(["docker", "compose", *args], timeout=timeout)


def start_stack() -> None:
    log("building and starting Docker stack")
    compose("up", "-d", "--build", "--remove-orphans", timeout=900)


def service_container(service: str) -> str:
    cid = compose("ps", "-q", service).stdout.strip()
    if not cid:
        raise E2EError(f"No container found for service {service}")
    return cid


def wait_service(service: str, *, timeout: int = 120) -> None:
    cid = service_container(service)

    def healthy():
        state = run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}",
                cid,
            ],
            timeout=10,
        ).stdout.strip()
        parts = state.split()
        if not parts or parts[0] != "running":
            return False
        return len(parts) == 1 or parts[1] == "healthy"

    wait_for(f"{service} to be healthy/running", healthy, timeout=timeout)
    log(f"{service} is ready")


def http_get(
    path: str,
    *,
    port: int = 8089,
    timeout: int = 8,
    headers: Optional[dict[str, str]] = None,
) -> tuple[int, bytes]:
    url = f"http://localhost:{port}{path}"
    request_headers = {"User-Agent": "takserver-e2e"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def http_post_json(
    path: str,
    payload: dict,
    *,
    port: int = 8089,
    timeout: int = 8,
) -> tuple[int, bytes]:
    url = f"http://localhost:{port}{path}"
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "takserver-e2e",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def wait_http_health() -> None:
    def healthy():
        status, body = http_get("/api/health")
        if status != 200:
            return False
        return json.loads(body.decode()) == {"status": "healthy"}

    wait_for("OpenTAKServer HTTP health", healthy, timeout=120)
    log("HTTP health endpoint is healthy")


def verify_admin_login() -> str:
    status, body = http_post_json(
        "/api/login?include_auth_token",
        {"username": "administrator", "password": "password"},
    )
    if status != 200:
        raise E2EError(f"admin login failed: HTTP {status} {body!r}")

    parsed = json.loads(body.decode())
    token = parsed.get("response", {}).get("user", {}).get("authentication_token")
    if not token:
        raise E2EError(f"admin login did not return an auth token: {body!r}")
    log("admin login succeeds")
    return token


def cot_xml(uid: str, callsign: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    stale = now + dt.timedelta(minutes=2)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_timestamp = stale.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return (
        f'<event version="2.0" uid="{uid}" type="a-f-A-M" how="m-g" '
        f'time="{timestamp}" start="{timestamp}" stale="{stale_timestamp}">'
        '<point lat="48.137" lon="11.575" hae="100" ce="5" le="5"/>'
        "<detail>"
        f'<contact callsign="{callsign}"/>'
        '<takv device="e2e" platform="Python" os="test" version="1.0"/>'
        "</detail>"
        "</event>"
    )


def send_tcp_cot(uid: str) -> None:
    payload = cot_xml(uid, uid.upper()).encode()

    def send():
        with socket.create_connection(("localhost", 8088), timeout=5) as sock:
            time.sleep(0.5)
            sock.sendall(payload)
            time.sleep(2.0)
        return True

    wait_for("TCP CoT listener", send, timeout=60, interval=2)
    log(f"sent TCP CoT {uid}")


def wait_cot_persisted(uid: str, *, timeout: int = 90) -> None:
    def persisted():
        status, body = http_get(f"/Marti/api/cot/xml/{uid}/all?secago=300")
        if status != 200:
            return False
        text = body.decode(errors="replace")
        return uid in text and "<events>" in text

    wait_for(f"CoT {uid} to be queryable", persisted, timeout=timeout, interval=2)
    log(f"CoT {uid} is queryable through Marti API")


def verify_cot_flow(label: str, uid_prefix: str, send_cot) -> str:
    last_error: Optional[Exception] = None
    for attempt in range(1, 4):
        uid = f"{uid_prefix}-{time.time_ns()}"
        try:
            send_cot(uid)
            wait_cot_persisted(uid, timeout=35)
            return uid
        except Exception as exc:  # noqa: BLE001 - retry the full network flow.
            last_error = exc
            log(f"{label} CoT attempt {attempt} did not complete: {exc}")
            time.sleep(2)

    raise E2EError(f"{label} CoT flow failed after 3 attempts: {last_error}")


def verify_map_state_has_last_point(uid: str, token: str) -> None:
    def has_last_point():
        status, body = http_get(
            "/api/map_state",
            headers={"Accept": "application/json", "Authentication-Token": token},
        )
        if status != 200:
            return False
        euds = json.loads(body.decode()).get("euds", [])
        eud = next((entry for entry in euds if entry.get("uid") == uid), None)
        if not eud:
            return False
        point = eud.get("last_point")
        if not point:
            return False
        return point.get("latitude") == 48.137 and point.get("longitude") == 11.575

    wait_for(f"map state last_point for {uid}", has_last_point, timeout=45, interval=2)
    log(f"map state includes last_point for {uid}")


def issue_admin_certificate() -> None:
    code = """
from opentakserver.app import create_app
from opentakserver.certificate_authority import CertificateAuthority
from opentakserver.extensions import logger

app = create_app(cli=True)
try:
    CertificateAuthority(logger, app).issue_certificate("administrator")
except RuntimeError as exc:
    if "Working outside of request context" not in str(exc):
        raise
"""
    log("issuing administrator client certificate for SSL E2E")
    compose("exec", "-T", "opentakserver", "python", "-c", code, timeout=120)


def read_container_file(path: str) -> bytes:
    return run_bytes(["docker", "compose", "exec", "-T", "opentakserver", "cat", path], timeout=30)


def send_ssl_cot(uid: str) -> None:
    issue_admin_certificate()
    with tempfile.TemporaryDirectory(prefix="tak-e2e-") as tmp:
        tmp_path = Path(tmp)
        cert = tmp_path / "administrator.pem"
        key = tmp_path / "administrator.nopass.key"
        ca = tmp_path / "ca.pem"

        cert.write_bytes(
            read_container_file(
                "/var/lib/opentakserver/ca/certs/administrator/administrator.pem"
            )
        )
        key.write_bytes(
            read_container_file(
                "/var/lib/opentakserver/ca/certs/administrator/administrator.nopass.key"
            )
        )
        ca.write_bytes(read_container_file("/var/lib/opentakserver/ca/ca.pem"))

        context = ssl.create_default_context(cafile=str(ca))
        context.check_hostname = False
        context.load_cert_chain(certfile=str(cert), keyfile=str(key))

        payload = cot_xml(uid, uid.upper()).encode()

        def send():
            raw_sock = socket.create_connection(("localhost", 8443), timeout=5)
            with context.wrap_socket(raw_sock, server_hostname="opentakserver") as sock:
                time.sleep(0.5)
                sock.sendall(payload)
                time.sleep(2.0)
            return True

        wait_for("SSL CoT listener", send, timeout=60, interval=2)
    log(f"sent SSL CoT {uid}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TAK Server Docker E2E checks")
    parser.add_argument("--no-start", action="store_true", help="Do not start/rebuild compose")
    parser.add_argument(
        "--skip-frontend",
        action="store_true",
        help="Do not clone/build OpenTAKServer-UI when server/frontend is missing",
    )
    parser.add_argument(
        "--skip-ssl-cot",
        action="store_true",
        help="Skip the authenticated SSL CoT send/persist check",
    )
    parser.add_argument("--ui-tag", default=UI_TAG, help=f"OpenTAKServer-UI tag (default: {UI_TAG})")
    args = parser.parse_args()

    try:
        if not args.skip_frontend:
            prepare_frontend(args.ui_tag)
        elif not (FRONTEND_DIR / "index.html").exists():
            raise E2EError("server/frontend/index.html is missing")

        if not args.no_start:
            start_stack()

        for service in ("postgres", "rabbitmq", "opentakserver", "cot_parser", "cot_tcp", "cot_ssl"):
            wait_service(service)

        # The CoT handlers do not expose a non-invasive health endpoint. Give the
        # listener processes a short runway, then prove readiness by sending CoT.
        time.sleep(3)

        wait_http_health()
        admin_token = verify_admin_login()

        status, body = http_get("/")
        if status != 200 or b"<html" not in body.lower():
            raise E2EError(f"Web UI root failed: HTTP {status}")
        log("Web UI root responds")

        status, body = http_get("/Marti/api/version/config")
        if status != 200 or b'"version":"1.7.12"' not in body:
            raise E2EError(f"Marti version check failed: HTTP {status} {body!r}")
        log("Marti version endpoint responds")

        tcp_uid = verify_cot_flow("TCP", "e2e-tcp", send_tcp_cot)
        verify_map_state_has_last_point(tcp_uid, admin_token)

        if not args.skip_ssl_cot:
            verify_cot_flow("SSL", "e2e-ssl", send_ssl_cot)

        log("all E2E checks passed")
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level test failure report.
        print(f"[e2e] FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
