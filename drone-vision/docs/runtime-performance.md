# Runtime And Performance

## Current Best Runtime

Use ONNX Runtime CoreML:

```bash
--onnx-provider coreml
```

Use this environment prefix when running from Codex or when CoreML has temp-directory issues:

```bash
TMPDIR=/private/tmp YOLO_CONFIG_DIR=outputs/ultralytics MPLCONFIGDIR=outputs/matplotlib
```

The `TMPDIR=/private/tmp` part matters because CoreML compilation failed in the default temp directory inside the Codex sandbox.

## Measured Detector Speed

Using the provided model:

```text
provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx
```

Measured on `Chase_Video.mp4`:

```text
Ultralytics ONNX CPU path:      about 42-45 ms/frame, about 22-23 FPS
Direct ONNX Runtime CPU path:   about 45 ms/frame, about 22 FPS
Direct ONNX Runtime CoreML:     about 10-11 ms/frame, about 90 FPS
```

CoreML batch run over all provided videos:

```text
Chase_Video:   4086 frames, avg processing FPS 89.73
DJI_Snow:     13959 frames, avg processing FPS 86.68
Video_8min:   14974 frames, avg processing FPS 88.24
Vibrations:   10722 frames, avg processing FPS 87.70
Vibrations2:  12119 frames, avg processing FPS 88.25
```

The CSV summaries from `outputs/coreml_all_video_logs` showed average per-frame detection latency around 11-12 ms.

## Why CPU Lagged

The original ONNX path ran through CPU inference at roughly 43 ms per frame. A 30 FPS video has only 33.3 ms per frame total, including decode, inference, overlay, display, and UI handling.

That means every-frame CPU detection cannot keep up with 30 FPS video. It must either:

- lag behind,
- drop frames,
- reduce detection frequency,
- run detection asynchronously, or
- use a faster runtime.

CoreML is the correct fix on this Mac for the provided ONNX model.

## MPS Status

PyTorch reports:

```text
mps_built True
mps_available False
```

Trying to allocate an MPS tensor fails in the current venv. Therefore `device=mps` is not the working acceleration route here.

Use CoreML for the provided ONNX model.

## ONNX Runtime Providers

The installed ONNX Runtime exposes:

```text
CoreMLExecutionProvider
AzureExecutionProvider
CPUExecutionProvider
```

The app can select providers with:

```text
--onnx-provider auto
--onnx-provider coreml
--onnx-provider cpu
--onnx-provider ultralytics
```

Use `coreml` for live preview and normal batch processing on this Mac.

Use `cpu` only to debug provider-specific issues.

Use `ultralytics` only if the direct ONNX decoder is incompatible with a future exported model.

## When To Use Async Detection

Use `--async-detection` when video playback stutters because inference blocks display.

With CoreML, the provided model is fast enough that synchronous every-frame detection is usually better:

```bash
--onnx-provider coreml --detection-interval 1 --realtime
```

If a future model is slower:

```bash
--onnx-provider coreml --async-detection --realtime
```

## When To Use Drop-Late-Frames

`--drop-late-frames` is useful for a live-file simulation where "current time" matters more than seeing every frame.

Do not use it when generating CSV metrics or annotated output, because it intentionally skips frames.

Use it only for preview:

```bash
--realtime --drop-late-frames
```

## Performance Caveats

- CSV writing and video decoding still cost time.
- Full annotated MP4 export is slower and consumes disk.
- OpenCV preview is basic; it is fine for testing, not a polished demo UI.
- The metrics panel FPS is processing throughput, not necessarily what the user perceives in the window.
