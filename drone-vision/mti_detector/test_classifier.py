"""Test: Bird/Drone classifier on best_video.mp4 frames.

Loads the pre-trained Keras .h5 model and classifies frames from best_video.
Logs drone detections with confidence scores.

Usage: python -m mti_detector.test_classifier
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

MODEL_PATH = "models/bird_drone_classifier_final.h5"
VIDEO_PATH = "recordings/best_video.mp4"

CLASS_LABELS = {0: "Bird", 1: "Drone"}
CONFIDENCE_THRESHOLD = 0.70
IMAGE_SIZE = (224, 224)


def preprocess(frame: np.ndarray) -> np.ndarray:
    img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, IMAGE_SIZE)
    img = img.astype(np.float32)
    if img.max() > 1.0:
        img /= 255.0
    return np.expand_dims(img, axis=0)


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
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"\nVideo: {VIDEO_PATH}")
    print(f"  {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}, "
          f"{fps:.0f} FPS, {total} frames")
    print(f"Confidence threshold: {CONFIDENCE_THRESHOLD}")
    print("-" * 60)

    drone_frames: list[tuple[int, float, float]] = []
    bird_frames = 0
    total_infer_ms = 0.0
    frame_i = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_i += 1

        batch = preprocess(frame)
        t0 = time.perf_counter()
        probs = model.predict(batch, verbose=0)[0]  # [bird_prob, drone_prob]
        dt = (time.perf_counter() - t0) * 1000
        total_infer_ms += dt

        drone_prob = float(probs[1])
        bird_prob = float(probs[0])

        if drone_prob >= CONFIDENCE_THRESHOLD:
            drone_frames.append((frame_i, drone_prob, dt))
            ts = frame_i / fps
            print(f"  DRONE  frame {frame_i:4d}  {ts:6.1f}s  "
                  f"drone={drone_prob:.3f}  bird={bird_prob:.3f}  {dt:.0f}ms")

        if frame_i % 30 == 0:
            print(f"  progress {frame_i}/{total}  "
                  f"last: bird={bird_prob:.2f}  drone={drone_prob:.2f}  {dt:.0f}ms")

    cap.release()
    elapsed = time.perf_counter()

    print()
    print("=" * 60)
    print(f"RESULTS")
    print(f"  Frames processed:       {frame_i}")
    print(f"  Total time:             {elapsed:.1f}s")
    print(f"  Avg inference:          {total_infer_ms / frame_i:.1f}ms")
    print(f"  Drone detections (>={CONFIDENCE_THRESHOLD}): {len(drone_frames)}")
    print(f"  Bird detections:        {bird_frames}")

    if drone_frames:
        min_p = min(f[1] for f in drone_frames)
        max_p = max(f[1] for f in drone_frames)
        print(f"  Best drone confidence:  {max_p:.3f} @ frame {drone_frames[0][0]}")
        print(f"  Drone confidence range: {min_p:.3f}–{max_p:.3f}")
        print(f"\n  All drone frames:")
        for fi, prob, ms in drone_frames:
            ts = fi / fps
            print(f"    frame {fi:4d}  {ts:6.1f}s  drone={prob:.3f}  {ms:.0f}ms")
    else:
        print(f"  No drone detections — model trained on close-up images, may not work on wide-angle frames")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
