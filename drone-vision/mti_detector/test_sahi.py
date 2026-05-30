"""Quick SAHI test — tile the frame and run YOLO on each tile.

Tests whether SAHI (Slicing Aided Hyper Inference) helps our existing
YOLO model detect small drones in ground-to-air video.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from drone_overlay.detection import (
    OnnxRuntimeYoloDetector,
    SahiDetector,
    Detection,
)


def main() -> int:
    source = "recordings/better_video.mp4"
    model_path = "provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx"

    base = OnnxRuntimeYoloDetector(model_path, provider="cpu", target_class="drone")
    sahi = SahiDetector(base, tile_size=320, overlap=0.2)

    cap = cv2.VideoCapture(source)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    print(f"Source: {source}  {total} frames")
    print(f"SAHI: tile=320 overlap=0.2  confidence=0.2")
    print("-" * 60)

    detections_total = 0
    frames_with_detections = 0
    started = time.perf_counter()
    frame_i = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_i += 1

        t0 = time.perf_counter()
        dets = sahi.predict(frame, confidence=0.20)
        dt = (time.perf_counter() - t0) * 1000

        if dets:
            frames_with_detections += 1
            detections_total += len(dets)

        if frame_i % 30 == 0 or frame_i == 1 or (dets and frame_i <= 10):
            best = max(dets, key=lambda d: d.confidence) if dets else None
            best_str = f"best: {best.label} {best.confidence:.2f} @ ({int(best.box.center_x)},{int(best.box.center_y)})" if best else "no detections"
            print(f"\r  frame {frame_i:4d}/{total}  {dt:5.0f}ms  {len(dets)} dets  {best_str}")

    elapsed = time.perf_counter() - started
    cap.release()

    print(f"\n{'=' * 60}")
    print(f"Frames: {frame_i}  Time: {elapsed:.1f}s  FPS: {frame_i / elapsed:.1f}")
    print(f"Frames with detections: {frames_with_detections}/{frame_i}")
    print(f"Total detections: {detections_total}")
    print(f"SAHI tile count estimate: {sahi._count_tiles(frame.shape) if hasattr(sahi, '_count_tiles') else 'N/A'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
