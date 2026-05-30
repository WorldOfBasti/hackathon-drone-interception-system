# Troubleshooting

## CoreML Fails To Compile

Symptom:

```text
Error compiling model: Failed to create a working directory appropriate for URL
```

Use:

```bash
TMPDIR=/private/tmp
```

Example:

```bash
TMPDIR=/private/tmp YOLO_CONFIG_DIR=outputs/ultralytics MPLCONFIGDIR=outputs/matplotlib \
.venv/bin/python detect_drone.py ...
```

In Codex, CoreML may also require running outside the normal sandbox. From a normal terminal, this should be less of an issue.

## Model Runs On CPU Instead Of CoreML

Check providers:

```bash
.venv/bin/python - <<'PY'
import onnxruntime as ort
print(ort.get_available_providers())
PY
```

You want:

```text
CoreMLExecutionProvider
```

Force CoreML:

```bash
--onnx-provider coreml
```

Force CPU for debugging:

```bash
--onnx-provider cpu
```

## Video Preview Lags

Use CoreML first:

```bash
--onnx-provider coreml
```

If the model is still slow:

```bash
--async-detection
```

If the video must stay close to wall-clock time:

```bash
--drop-late-frames
```

Do not use `--drop-late-frames` for evaluation logs, because it intentionally skips frames.

## Circle Jumps To Wrong Object

Tighten live filters:

```bash
--confidence 0.50
--confirm-frames 2
--max-jump-pixels 180
--max-detections 10
```

If this hides real drones, back off:

```bash
--confidence 0.40
--max-jump-pixels 260
--max-detections 20
```

With `--max-jump-pixels` set, the app now prefers detections near the current marker before
accepting a far-away higher-confidence box. If the real drone crosses the frame very quickly,
an over-tight jump gate can still hold the old target too long.

## Track Drops In Clutter Even Though The Drone Is Still Nearby

Use lower gated reacquisition:

```bash
--confidence 0.35
--reacquire-confidence 0.20
--max-jump-pixels 240
```

The lower threshold only helps after a track exists and only for boxes near the current marker.
This is safer than globally lowering `--confidence`, but it is not free: if clutter sits right
next to the drone, a very low value can make the tracker cling to the wrong local detail.

## Marker Freezes During Brief Occlusions

Use short motion prediction:

```bash
--prediction-decay 0.85
--max-prediction-frames 4
```

This moves the marker using recent velocity when the detector misses a few frames. It is useful
when the drone briefly crosses buildings or textured backgrounds. Do not crank it too high: after
longer occlusions, prediction is just a guess and can drift onto the wrong object.

## Circle Flickers

Increase persistence:

```bash
--max-missing 8
```

Smooth more:

```bash
--smoothing-alpha 0.30
```

Follow movement faster:

```bash
--smoothing-alpha 0.60
```

## Too Many False Positives

Raise confidence:

```bash
--confidence 0.55
```

Require confirmation:

```bash
--confirm-frames 2
```

Suppress duplicate boxes and keep fewer candidates:

```bash
--iou-threshold 0.45
--max-detections 10
```

This reduces junk detections but can delay first marker appearance.

## Missing Small Or Distant Drones

Lower confidence:

```bash
--confidence 0.25
```

Use fewer filters:

```bash
--confirm-frames 1
```

If the model still misses them, it is a model/data problem. Add those misses to the training set.

## OpenCV Window Does Not Appear

Check that you did not pass:

```bash
--no-preview
```

The window title is:

```text
Drone Detection - <video name>
```

It may open behind other windows.

## Ultralytics Writes Config Warnings

Use local writable config/cache directories:

```bash
YOLO_CONFIG_DIR=outputs/ultralytics MPLCONFIGDIR=outputs/matplotlib
```

## PyTorch MPS Does Not Work

Current venv showed:

```text
mps_built True
mps_available False
```

Do not rely on:

```bash
--device mps
```

for this project unless a fresh check passes.

Use:

```bash
--onnx-provider coreml
```

for the provided ONNX model.

## No Space Left On Device

Check disk:

```bash
df -h .
```

Find large local folders:

```bash
du -sh provided_data/* outputs datasets .venv 2>/dev/null
```

Likely cleanup targets:

```text
provided_data/compressed
outputs/*_annotated.mp4
outputs/baseline_videos
```

Only delete archives or generated outputs if you are sure they are duplicated or not needed.
