#!/usr/bin/env python3
"""E2E smoke test for the Three.js Triangometry viewer.

Uses local Chrome headless to render a real page screenshot and verifies that
the scene contains visible non-background geometry. No Python packages needed.
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.request
import zlib
from pathlib import Path


CHROME_CANDIDATES = [
    "/Applications/Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    for name in ("google-chrome", "chromium", "chrome"):
        try:
            result = subprocess.run(
                ["which", name],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            continue
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    raise SystemExit("Chrome/Chromium was not found for E2E screenshot testing.")


def wait_for_health(url: str, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=0.5) as response:
                if response.read().decode("utf-8").strip() == "ok":
                    return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"viewer did not become healthy at {url}")


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def start_server(data_dir: str, port: int) -> subprocess.Popen[str] | None:
    if is_port_open(port):
        return None
    return subprocess.Popen(
        [
            sys.executable,
            "-u",
            "drone_map_three.py",
            "--data",
            data_dir,
            "--no-open",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def png_pixels(path: Path) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"{path} is not a PNG")

    offset = 8
    width = height = None
    color_type = None
    bit_depth = None
    compressed = bytearray()
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        offset += 12 + length

        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk_data[:10])
        elif chunk_type == b"IDAT":
            compressed.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    if width is None or height is None or bit_depth != 8 or color_type not in {2, 6}:
        raise RuntimeError(f"unsupported PNG format in {path}")

    channels = 4 if color_type == 6 else 3
    raw = zlib.decompress(bytes(compressed))
    stride = width * channels
    pixels: list[tuple[int, int, int, int]] = []
    cursor = 0
    previous = [0] * stride

    for _row in range(height):
        filter_type = raw[cursor]
        cursor += 1
        current = list(raw[cursor : cursor + stride])
        cursor += stride

        for idx in range(stride):
            left = current[idx - channels] if idx >= channels else 0
            up = previous[idx]
            up_left = previous[idx - channels] if idx >= channels else 0
            if filter_type == 1:
                current[idx] = (current[idx] + left) & 0xFF
            elif filter_type == 2:
                current[idx] = (current[idx] + up) & 0xFF
            elif filter_type == 3:
                current[idx] = (current[idx] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                current[idx] = (current[idx] + paeth(left, up, up_left)) & 0xFF
            elif filter_type != 0:
                raise RuntimeError(f"unsupported PNG filter {filter_type}")

        for idx in range(0, stride, channels):
            r, g, b = current[idx : idx + 3]
            a = current[idx + 3] if channels == 4 else 255
            pixels.append((r, g, b, a))
        previous = current

    return width, height, pixels


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def count_scene_pixels(path: Path) -> int:
    width, height, pixels = png_pixels(path)
    count = 0
    for y in range(int(height * 0.18), int(height * 0.88)):
        row = y * width
        for x in range(int(width * 0.22), int(width * 0.94)):
            r, g, b, _a = pixels[row + x]
            # Light background is near #f6f8fb; this catches grid, paths, drone,
            # labels, and dark-mode fallback if the test is run that way.
            if abs(r - 246) + abs(g - 248) + abs(b - 251) > 42:
                count += 1
    return count


def run_chrome(
    chrome: str,
    url: str,
    screenshot: Path,
    log_path: Path,
    mode: str,
) -> None:
    args = [
        chrome,
        "--headless=new",
        "--window-size=2048,737",
        f"--screenshot={screenshot}",
        url,
    ]
    if mode == "fallback":
        args.insert(2, "--disable-gpu")
    elif mode == "webgl":
        args.insert(2, "--use-angle=swiftshader")
        args.insert(3, "--enable-unsafe-swiftshader")

    result = subprocess.run(args, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log_path.write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"Chrome screenshot failed for {mode}; see {log_path}")
    if not screenshot.exists():
        raise RuntimeError(f"Chrome did not write {screenshot}")

    bad_console = re.search(r"INFO:CONSOLE.*(?:Uncaught|TypeError|ReferenceError|SyntaxError)", result.stdout)
    if bad_console:
        raise RuntimeError(f"console error in {mode}: {bad_console.group(0)}")

    visible_pixels = count_scene_pixels(screenshot)
    if visible_pixels < 800:
        raise RuntimeError(f"scene looks blank in {mode}: only {visible_pixels} non-background pixels")
    print(f"{mode}: {visible_pixels} visible scene pixels in {screenshot}")


def main() -> None:
    parser = argparse.ArgumentParser(description="E2E screenshot test for the Triangometry Three.js viewer.")
    parser.add_argument("--data", default="data")
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--keep-server", action="store_true")
    args = parser.parse_args()

    server = start_server(args.data, args.port)
    url = f"http://127.0.0.1:{args.port}"
    try:
        wait_for_health(url)
        chrome = find_chrome()
        test_url = f"{url}/?e2e={int(time.time() * 1000)}"
        run_chrome(
            chrome,
            test_url,
            Path("/tmp/triangometry_three_e2e_webgl.png"),
            Path("/tmp/triangometry_three_e2e_webgl.log"),
            "webgl",
        )
        run_chrome(
            chrome,
            f"{test_url}&mode=fallback",
            Path("/tmp/triangometry_three_e2e_fallback.png"),
            Path("/tmp/triangometry_three_e2e_fallback.log"),
            "fallback",
        )
    finally:
        if server is not None and not args.keep_server:
            server.terminate()
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=3)


if __name__ == "__main__":
    main()
