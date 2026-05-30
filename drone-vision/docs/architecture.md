# Architecture

## Pipeline

```text
video source
  -> OpenCV frame read
  -> detector
  -> confidence/class filtering
  -> NMS and max-detection limiting
  -> tracker-aware primary target selection and gated reacquisition
  -> single-target tracker/smoother and short-miss prediction
  -> circle overlay
  -> preview window
  -> optional annotated video
  -> optional CSV log
```

## Modules

```text
detect_drone.py
  Thin CLI entry point. Calls drone_overlay.cli.main().

drone_overlay/cli.py
  Parses CLI arguments, expands video directories into file lists, creates
  VideoProcessorConfig, and calls process_video().

drone_overlay/video.py
  Owns the video loop. Handles OpenCV capture, preview controls, export writer,
  CSV logger, realtime pacing, late-frame dropping, and optional async inference.

drone_overlay/detection.py
  Defines Detection, Detector protocol, detector factory, Ultralytics adapter,
  and direct ONNX Runtime adapter.

drone_overlay/tracking.py
  Maintains one smoothed target marker. Handles missing frames, target
  confirmation, and jump rejection.

drone_overlay/geometry.py
  BoundingBox and CircleMarker primitives plus bbox-to-circle conversion.

drone_overlay/overlay.py
  Draws marker, label, and metrics panel onto BGR frames.

drone_overlay/metrics.py
  Rolling FPS, per-frame metrics, and CSV writer.

tools/convert_coco_to_yolo.py
  Converts Roboflow COCO object-detection exports into YOLO directory format.
```

## Detector Paths

### ONNX Runtime Path

For `.onnx` models, `create_detector()` returns `OnnxRuntimeYoloDetector` unless `--onnx-provider ultralytics` is passed.

Supported providers:

```text
auto       prefer CoreML when ONNX Runtime exposes CoreMLExecutionProvider
coreml     force CoreMLExecutionProvider plus CPU fallback
cpu        force CPUExecutionProvider
ultralytics use the Ultralytics YOLO wrapper instead
```

The direct ONNX path preprocesses frames itself:

```text
BGR frame
  -> letterbox resize to imgsz x imgsz
  -> BGR to RGB
  -> CHW float32 normalized tensor
  -> ONNX Runtime session
  -> YOLO output decode
  -> confidence/class filtering
  -> non-max suppression
  -> BoundingBox pixel coordinates
```

The provided model output is shaped like:

```text
1 x 5 x 8400
```

For this single-class model:

```text
x_center, y_center, width, height, drone_confidence
```

### Ultralytics Path

For `.pt` models or when `--onnx-provider ultralytics` is used, the app uses the Ultralytics `YOLO` wrapper.

This path is convenient for new `.pt` training outputs, but the provided ONNX model was much slower through Ultralytics/CPU than through direct ONNX Runtime/CoreML.

## Tracking And Stability

The tracker is single-target. It is intentionally simple for MVP use.

Features:

- Exponential smoothing of center and radius.
- Recently-lost persistence for short missed detections.
- Decaying constant-velocity prediction for short missed detections.
- New-target confirmation using `--confirm-frames`.
- Large jump rejection using `--max-jump-pixels`.
- Primary-target selection prefers detections within the current target's jump gate before
  considering a higher-confidence far-away box.
- When a marker already exists, inference can run at `--reacquire-confidence`; those weaker boxes
  are accepted only if they are near the current/predicted marker.

Important behavior:

- Skipped detector frames are not treated as misses.
- A true detector miss calls `tracker.update(None)`.
- A large jump becomes a candidate, not an immediate marker replacement.
- If the jump persists, it can become the new target.
- If another detection remains near the current marker, that nearby detection wins over a
  farther higher-confidence box.
- Weak far-away boxes below the main `--confidence` threshold are treated as misses instead of
  becoming jump candidates.
- During a detector miss, the marker can move along the last observed velocity for
  `--max-prediction-frames`, then fall back to a stationary recently-lost marker.

## Preview Modes

### Synchronous Detection

Default behavior:

```text
read frame -> run detector -> draw -> display
```

This gives the freshest overlay but can stall playback if inference is slow.

### Async Detection

With `--async-detection`:

```text
display thread reads/draws frames
background worker runs detector on newest submitted frame
stale pending frames are overwritten
```

This keeps video playback smoother if inference is slow, at the cost of overlay updates arriving later.

After CoreML acceleration, async detection is usually not required for the provided model.

## Realtime Pacing

`--realtime` changes preview wait time based on source FPS:

```text
wait = frame_period - processing_time
```

If processing is faster than source FPS, playback looks natural. If processing is slower, the app cannot make time go backward. In that case:

- `--async-detection` keeps display smooth.
- `--drop-late-frames` skips ahead in file playback.
- CoreML acceleration is the preferred fix.

## Output Files

CSV rows:

```text
video_name,frame_number,timestamp,detected,confidence,center_x,center_y,radius,fps,avg_fps,latency_ms
```

Annotated video:

```text
original frame + circle marker + confidence label + metrics panel
```

Generated outputs are written under `outputs/` by convention.
