"""MOG2-only pass — save foreground masks and comparison frames for presentation.

Fast: no YOLO, just background subtraction + morph cleanup.
Outputs:
  - side-by-side video: Original | MOG2 Mask
  - frame snapshots: every Nth frame saved as PNG

Usage:
    python -m mti_detector.save_mog2_masks recordings/test_detection_base.mp4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from mti_detector.bg_subtraction import BackgroundSubtractor, MotionCompensatedSubtractor


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="MOG2-only — save moving-pixel masks")
    p.add_argument("source", help="Video file path")
    p.add_argument("--output", default=None, help="Output video path (default: <stem>_mog2.mp4)")
    p.add_argument("--snapshot-every", type=int, default=60, help="Save PNG every N frames (0=off)")
    p.add_argument("--warmup", type=int, default=60, help="Warmup frames")
    p.add_argument("--var-threshold", type=int, default=28)
    p.add_argument("--learning-rate", type=float, default=0.001)
    p.add_argument("--max-frames", type=int, default=0, help="Stop after N frames (0=all)")
    p.add_argument("--no-motion-comp", action="store_true", help="Disable motion compensation")
    args = p.parse_args(argv)

    source = Path(args.source)
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        print(f"error: cannot open {source}")
        return 1

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    max_frames = args.max_frames if args.max_frames > 0 else total

    output_path = Path(args.output or f"{source.stem}_mog2.mp4")
    out_dir = output_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    snap_dir = out_dir / f"{source.stem}_mog2_snapshots"
    if args.snapshot_every > 0:
        snap_dir.mkdir(parents=True, exist_ok=True)

    panel_w = width * 3
    panel_h = height + 40
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (panel_w, panel_h))

    if args.no_motion_comp:
        bg = BackgroundSubtractor(
            history=250,
            var_threshold=args.var_threshold,
            learning_rate=args.learning_rate,
        )
    else:
        bg = MotionCompensatedSubtractor(
            history=250,
            var_threshold=args.var_threshold,
            learning_rate=args.learning_rate,
        )

    print(f"Source: {source.name}  {width}x{height}  {fps:.0f} FPS  {total} frames")
    print(f"Output: {output_path}")
    print(f"Warmup: {args.warmup}  varThreshold={args.var_threshold}  motionComp={not args.no_motion_comp}")

    frame_i = 0
    while frame_i < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        frame_i += 1

        fg = bg.apply(frame)
        status = "warmup" if frame_i <= args.warmup else "active"

        fg_colored = cv2.bitwise_and(frame, frame, mask=fg)

        panel = np.zeros((panel_h, panel_w, 3), dtype=np.uint8)
        panel[0:height, 0:width] = frame
        panel[0:height, width:width * 2] = cv2.cvtColor(fg, cv2.COLOR_GRAY2BGR)
        panel[0:height, width * 2:width * 3] = fg_colored

        fg_pct = int((fg > 0).sum() / (width * height) * 1000) / 10
        cv2.putText(panel, "Original", (10, height - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(panel, "MOG2 Maske", (width + 10, height - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(panel, f"Bewegte Pixel ({fg_pct:.1f}%)", (width * 2 + 10, height - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(panel, f"Frame {frame_i}/{max_frames}  [{status}]",
                    (10, panel_h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
        writer.write(panel)

        if args.snapshot_every > 0 and frame_i % args.snapshot_every == 0:
            snap_path = snap_dir / f"frame_{frame_i:04d}.png"
            cv2.imwrite(str(snap_path), panel)

        if frame_i % 30 == 0:
            print(f"\r  {frame_i}/{max_frames}  fg={fg_pct:.1f}%  [{status}]", end="", flush=True)

    cap.release()
    writer.release()
    size_mb = output_path.stat().st_size / 1e6
    print(f"\nDone: {output_path} ({size_mb:.1f} MB)  {frame_i} frames")
    if args.snapshot_every:
        snaps = list(snap_dir.glob("*.png"))
        print(f"Snaps: {len(snaps)} PNGs in {snap_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
