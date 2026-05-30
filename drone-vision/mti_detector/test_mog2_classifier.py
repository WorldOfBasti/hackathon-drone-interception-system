"""Test: MOG2 (ultra-sensitive) → ROI crops → Bird/Drone Classifier.

Combines MOG2 foreground detection with the Keras classifier.
MOG2 finds ANY motion, classifier filters false positives.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

import cv2
import numpy as np

MODEL_PATH = "models/bird_drone_classifier_final.h5"
VIDEO_PATH = "recordings/best_video.mp4"

MOG2_PARAMS = dict(
    history=500,
    varThreshold=4,     # ultra-sensitive
    detectShadows=False,
)
MIN_ROI_AREA = 16       # minimum contour area (pixels)
ROI_PAD = 16             # pixels to pad around ROI
CONFIDENCE_THRESHOLD = 0.6


@dataclass
class ClassifierResult:
    frame_idx: int
    timestamp_s: float
    x: int
    y: int
    w: int
    h: int
    drone_prob: float
    bird_prob: float
    label: str
    inference_ms: float


def preprocess(patch_bgr: np.ndarray) -> np.ndarray:
    """Resize BGR patch to 224x224 RGB, normalize, batchify."""
    img = cv2.resize(patch_bgr, (224, 224))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.astype(np.float32) / 255.0
    return np.expand_dims(img, axis=0)


def extract_rois(fg_mask: np.ndarray, min_area: int, pad: int,
                 frame_w: int, frame_h: int) -> list[tuple[int, int, int, int]]:
    """Return list of (x, y, w, h) ROIs from foreground mask contours."""
    contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rois = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        x = max(0, x - pad)
        y = max(0, y - pad)
        w = min(frame_w - x, w + 2 * pad)
        h = min(frame_h - y, h + 2 * pad)
        rois.append((x, y, w, h))
    return rois


def main() -> int:
    if not Path(VIDEO_PATH).exists():
        print(f"Missing demo video: {VIDEO_PATH}")
        print("Add your own test video before running this script.")
        return 1

    import tensorflow as tf

    tf.get_logger().setLevel("ERROR")

    print(f"Loading model: {MODEL_PATH}")
    t0 = time.perf_counter()
    model = tf.keras.models.load_model(MODEL_PATH, compile=False)
    print(f"  loaded in {(time.perf_counter() - t0) * 1000:.0f}ms")

    cap = cv2.VideoCapture(VIDEO_PATH)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    fps_val = cap.get(cv2.CAP_PROP_FPS)
    fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"\nVideo: {VIDEO_PATH}  {fw}x{fh}  {fps_val:.0f}fps  {total} frames")
    print(f"MOG2: varThreshold={MOG2_PARAMS['varThreshold']}  minArea={MIN_ROI_AREA}  pad={ROI_PAD}")
    print(f"Classifier: threshold={CONFIDENCE_THRESHOLD}")
    print("-" * 60)

    mog2 = cv2.createBackgroundSubtractorMOG2(**MOG2_PARAMS)
    results: List[ClassifierResult] = []
    frame_i = 0
    total_mog2_ms = 0.0
    total_cls_ms = 0.0
    frames_with_rois = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_i += 1

        t0 = time.perf_counter()
        fg_mask = mog2.apply(frame, learningRate=-1)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mog2_ms = (time.perf_counter() - t0) * 1000
        total_mog2_ms += mog2_ms

        rois = extract_rois(fg_mask, MIN_ROI_AREA, ROI_PAD, fw, fh)

        if rois:
            frames_with_rois += 1

        for x, y, w, h in rois:
            patch = frame[y:y + h, x:x + w]
            batch = preprocess(patch)
            t0 = time.perf_counter()
            probs = model.predict(batch, verbose=0)[0]
            cls_ms = (time.perf_counter() - t0) * 1000
            total_cls_ms += cls_ms

            drone_prob = float(probs[1])
            bird_prob = float(probs[0])
            label = "Drone" if drone_prob >= CONFIDENCE_THRESHOLD else "Bird"
            ts = frame_i / fps_val

            results.append(ClassifierResult(
                frame_i, ts, x, y, w, h, drone_prob, bird_prob, label, cls_ms,
            ))

        if frame_i % 30 == 0:
            n_rois = len(rois)
            fg_pct = np.count_nonzero(fg_mask) / (fw * fh) * 100
            print(f"  frame {frame_i:4d}/{total}  fg={fg_pct:.1f}%  "
                  f"ROIs={n_rois}  MOG2={mog2_ms:.0f}ms  "
                  f"drones={sum(1 for r in results[-n_rois:] if r.label == 'Drone') if n_rois else 0}")

    cap.release()

    print()
    print("=" * 60)
    print(f"RESULTS")
    print(f"  Frames processed:        {frame_i}")
    print(f"  Frames with ROIs:        {frames_with_rois}")
    print(f"  Total ROIs extracted:    {len(results)}")
    print(f"  Avg MOG2 time:           {total_mog2_ms / frame_i:.1f}ms")
    if results:
        print(f"  Avg classifier time:     {total_cls_ms / len(results):.1f}ms")

    drones = [r for r in results if r.label == "Drone"]
    birds = [r for r in results if r.label == "Bird"]

    print(f"\n  Drone detections:  {len(drones)}")
    print(f"  Bird detections:   {len(birds)}")

    if drones:
        best = max(drones, key=lambda r: r.drone_prob)
        print(f"\n  Drone detections:")
        for r in drones:
            print(f"    frame {r.frame_idx:4d}  {r.timestamp_s:6.1f}s  "
                  f"({r.x:3d},{r.y:3d} {r.w:3d}x{r.h:3d})  "
                  f"drone={r.drone_prob:.3f}  bird={r.bird_prob:.3f}  {r.inference_ms:.0f}ms")

    if birds:
        best_bird = max(birds, key=lambda r: r.bird_prob)
        print(f"\n  Bird detections (top 10):")
        for r in sorted(birds, key=lambda r: r.bird_prob, reverse=True)[:10]:
            print(f"    frame {r.frame_idx:4d}  {r.timestamp_s:6.1f}s  "
                  f"({r.x:3d},{r.y:3d} {r.w:3d}x{r.h:3d})  "
                  f"bird={r.bird_prob:.3f}  drone={r.drone_prob:.3f}")

    avg_drone_conf = np.mean([r.drone_prob for r in drones]) if drones else 0
    print(f"\n  Avg drone confidence:    {avg_drone_conf:.3f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
