"""Synthetic drone video generator for MTI pipeline testing.

Generates an MP4 video with a static sky background and a small
moving drone. No camera, no real drone needed.

Usage:
    python -m mti_detector.fake_drone_video
    python -m mti_detector.fake_drone_video --duration 10 --size 1280x720
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import cv2
import numpy as np


def make_sky_gradient(height: int, width: int) -> np.ndarray:
    """Render a blue sky gradient (lighter at horizon, darker at zenith)."""
    sky = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        t = y / height
        b = int(180 + 55 * t)
        g = int(180 + 40 * t)
        r = int(100 + 155 * t)
        sky[y, :] = (b, g, r)
    return sky


def make_clouds(frame: np.ndarray, seed: int = 42) -> np.ndarray:
    """Add a few subtle static clouds to the sky."""
    rng = np.random.RandomState(seed)
    h, w = frame.shape[:2]
    for _ in range(3):
        cx, cy = rng.randint(0, w), rng.randint(0, h // 2)
        rx, ry = rng.randint(80, 200), rng.randint(20, 50)
        overlay = frame.copy()
        cv2.ellipse(overlay, (cx, cy), (rx, ry), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(overlay, (cx + rx // 2, cy), (rx // 2, ry // 2), 0, 0, 360, (255, 255, 255), -1)
        frame = cv2.addWeighted(frame, 0.92, overlay, 0.08, 0)
    return frame


def make_drone(
    drone_path: list[tuple[int, int]],
    frame_number: int,
    height: int,
    width: int,
) -> tuple[int, int] | None:
    """Return (x, y) position of drone at frame_number, or None if out of frame."""
    if not drone_path:
        return None
    total = len(drone_path)
    t = frame_number % (total * 2)
    if t < total:
        idx = t
    else:
        idx = (total * 2 - 1) - t
    idx = max(0, min(total - 1, idx))
    x, y = drone_path[idx]
    if x < 0 or x >= width or y < 0 or y >= height:
        return None
    return x, y


def draw_drone(frame: np.ndarray, x: int, y: int, size: int = 6) -> None:
    """Draw a small drone silhouette (dark cross/star shape)."""
    cv2.circle(frame, (x, y), size, (40, 40, 40), -1)
    cv2.line(frame, (x - size - 1, y), (x + size + 1, y), (60, 60, 60), 1)
    cv2.line(frame, (x, y - size - 1), (x, y + size + 1), (60, 60, 60), 1)
    cv2.circle(frame, (x, y), size, (40, 40, 40), -1)


def build_drone_path(width: int, height: int, pattern: str = "diagonal") -> list[tuple[int, int]]:
    """Build a flight path across the frame.

    Patterns:
        diagonal  - fly from bottom-left to top-right
        sine      - fly horizontally with vertical oscillation
        circle    - fly a circular path
        hover     - centered, tiny drift
    """
    steps = 180
    margin = 100

    if pattern == "diagonal":
        x0, y0 = margin, height - margin
        x1, y1 = width - margin, margin
        return [(int(x0 + (x1 - x0) * i / steps),
                 int(y0 + (y1 - y0) * i / steps)) for i in range(steps)]

    elif pattern == "sine":
        return [(int(margin + (width - 2 * margin) * i / steps),
                 int(height / 2 + 80 * math.sin(i * 0.15))) for i in range(steps)]

    elif pattern == "circle":
        cx, cy = width // 2, height // 2
        r = min(width, height) // 3
        return [(int(cx + r * math.cos(i * 2 * math.pi / steps)),
                 int(cy + r * math.sin(i * 2 * math.pi / steps))) for i in range(steps)]

    elif pattern == "hover":
        cx, cy = width // 2, height // 2
        return [(int(cx + 10 * math.sin(i * 0.3)),
                 int(cy + 10 * math.cos(i * 0.25))) for i in range(steps)]

    else:
        raise ValueError(f"Unknown pattern: {pattern}")


def generate(
    output: str = "synthetic_drone.mp4",
    duration: float = 10.0,
    fps: int = 30,
    width: int = 1280,
    height: int = 720,
    pattern: str = "diagonal",
    drone_size: int = 6,
    cloud_seed: int = 42,
) -> str:
    """Generate synthetic drone video and return output path."""
    total_frames = int(duration * fps)
    output_path = Path(output).resolve()

    fourcc = cv2.VideoWriter_fourcc(*"avc1")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
    if not writer.isOpened():
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"Cannot open video writer for {output_path}")

    sky_base = make_sky_gradient(height, width)
    sky_base = make_clouds(sky_base, cloud_seed)
    drone_path = build_drone_path(width, height, pattern)

    print(f"Generating {output_path}")
    print(f"  {width}x{height}  {fps} FPS  {duration}s  {total_frames} frames")
    print(f"  pattern={pattern}  drone_size={drone_size}")

    for i in range(total_frames):
        frame = sky_base.copy()
        pos = make_drone(drone_path, i, height, width)
        if pos is not None:
            draw_drone(frame, pos[0], pos[1], drone_size)
        writer.write(frame)

        if i % (total_frames // 10 + 1) == 0 or i == total_frames - 1:
            pct = 100 * (i + 1) / total_frames
            print(f"\r  frame {i + 1}/{total_frames} ({pct:.0f}%)", end="", flush=True)

    writer.release()
    print(f"\nDone: {output_path}  ({output_path.stat().st_size / 1e6:.1f} MB)")
    return str(output_path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate synthetic drone video for MTI testing")
    p.add_argument("--output", default="synthetic_drone.mp4", help="Output file path")
    p.add_argument("--duration", type=float, default=15.0, help="Video duration in seconds")
    p.add_argument("--fps", type=int, default=30, help="Frames per second")
    p.add_argument("--size", default="1280x720", help="WidthxHeight (e.g. 1280x720)")
    p.add_argument("--pattern", default="diagonal", choices=["diagonal", "sine", "circle", "hover"])
    p.add_argument("--drone-size", type=int, default=6, help="Drone dot radius in pixels")
    p.add_argument("--cloud-seed", type=int, default=42, help="Random seed for cloud placement")
    args = p.parse_args(argv)

    w_str, h_str = args.size.split("x")
    w, h = int(w_str), int(h_str)

    generate(
        output=args.output,
        duration=args.duration,
        fps=args.fps,
        width=w,
        height=h,
        pattern=args.pattern,
        drone_size=args.drone_size,
        cloud_seed=args.cloud_seed,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
