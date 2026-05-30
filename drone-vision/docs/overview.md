# Project Overview

## Purpose

This project is a local MVP for testing drone detection on video. It loads video files or OpenCV-compatible sources, runs a detector, draws a visible circle around the detected drone, shows performance metrics, and can save annotated output or CSV logs.

The project is meant to answer practical questions:

- Does the provided model detect drones in the available videos?
- How fast does inference run on this Mac?
- Does the overlay feel usable in a live preview?
- Where does the model fail?
- Which videos/settings should be used for demos or further training?

## What Exists Now

- CLI app: `detect_drone.py`
- Python package: `drone_overlay`
- Provided videos under `provided_data/`
- Provided single-class drone ONNX model:
  `provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx`
- Roboflow COCO export:
  `provided_data/daedalus-hackaburg.coco-004/train/_annotations.coco.json`
- COCO-to-YOLO converter:
  `tools/convert_coco_to_yolo.py`
- Regression tests under `tests/`

## Current Best Live Mode

Use the provided ONNX model with ONNX Runtime CoreML:

```bash
TMPDIR=/private/tmp YOLO_CONFIG_DIR=outputs/ultralytics MPLCONFIGDIR=outputs/matplotlib \
.venv/bin/python detect_drone.py \
  --source "provided_data/Air-to-Air 2/Chase_Video.mp4" \
  --model "provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx" \
  --confidence 0.45 \
  --detection-interval 1 \
  --confirm-frames 2 \
  --max-jump-pixels 240 \
  --reacquire-confidence 0.20 \
  --iou-threshold 0.45 \
  --max-detections 20 \
  --max-missing 6 \
  --prediction-decay 0.85 \
  --max-prediction-frames 4 \
  --imgsz 640 \
  --onnx-provider coreml \
  --realtime
```

The high-level reason for these flags:

- `--onnx-provider coreml`: uses Apple acceleration instead of CPU.
- `--realtime`: paces video playback to source FPS.
- `--confidence 0.45`: reduces weak false positives.
- `--confirm-frames 2`: avoids showing one-frame junk detections.
- `--reacquire-confidence 0.20`: keeps weak nearby boxes available for an existing track.
- `--iou-threshold 0.45`: removes duplicate overlapping boxes before target selection.
- `--max-detections 20`: keeps postprocessing bounded and avoids chasing junk tails.
- `--max-jump-pixels 240`: rejects sudden far-away target jumps unless they persist.
- `--prediction-decay 0.85`: slows the extrapolated velocity on each missed frame.
- `--max-prediction-frames 4`: predicts only short detector dropouts to limit drift.

## Current Data Inventory

Provided videos:

```text
provided_data/Air-to-Air 2/Chase_Video.mp4
provided_data/Air-to-Air 2/DJI_Snow.MP4
provided_data/Air-to-Air/Video_8min.mp4
provided_data/drive-download-20260528T184848Z-3-001/Air-to-Air/Vibrations.mp4
provided_data/drive-download-20260528T184848Z-3-001/Air-to-Air/Vibrations2.mp4
```

Provided trained model:

```text
provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx
```

Known model metadata:

```text
Task: detect
Class names: {0: 'drone'}
Input: 1 x 3 x 640 x 640
Output: 1 x 5 x 8400
```

Roboflow dataset:

```text
59752 images
61401 annotations
0 unlabeled images
single active category: drone
mostly 640 x 480 images
```

## Acceptance Status Against PRD

Implemented:

- Load video files.
- Run drone detection.
- Draw circle overlay.
- Show FPS, confidence, latency, frame number, timestamp.
- Change confidence threshold at runtime.
- Save CSV logs.
- Save annotated videos.
- Smooth marker and preserve recently lost targets.
- Prefer plausible detections near the current target before accepting far-away jumps.
- Allow lower-confidence detections to continue an existing nearby target.
- Predict short missing spans from recent marker velocity.
- Suppress duplicate ONNX boxes with NMS.
- CoreML acceleration for provided ONNX model.
- Basic live preview.

Partially implemented:

- Live camera/stream input is supported if OpenCV can open the source, but not deeply validated.
- Multi-video testing works, but there is no GUI file picker.
- Tracking is lightweight single-target smoothing, not production tracking.

Not implemented:

- Multi-drone tracking.
- FPV/goggles integration.
- Production UI.
- Distance estimation.
- Autonomous control.
