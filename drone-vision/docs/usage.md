# Usage Guide

## Environment Setup

```bash
cd .
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install onnxruntime onnx
```

`onnxruntime` and `onnx` are needed for the provided `.onnx` model path. The app still supports Ultralytics `.pt` models, but the provided working drone model is ONNX.

## Live Preview

Best current command:

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

Controls while preview is open:

```text
q or Esc     quit
Space        pause/resume
n or .       step one frame while paused
r            restart video file
o            toggle overlay
c            toggle confidence text
+ or =       raise confidence threshold
- or _       lower confidence threshold
```

## Process One Video Headlessly

```bash
TMPDIR=/private/tmp YOLO_CONFIG_DIR=outputs/ultralytics MPLCONFIGDIR=outputs/matplotlib \
.venv/bin/python detect_drone.py \
  --source "provided_data/Air-to-Air 2/Chase_Video.mp4" \
  --model "provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx" \
  --confidence 0.35 \
  --reacquire-confidence 0.20 \
  --iou-threshold 0.45 \
  --max-detections 20 \
  --onnx-provider coreml \
  --no-preview \
  --csv-log outputs/chase_coreml.csv
```

## Export Annotated Video

```bash
TMPDIR=/private/tmp YOLO_CONFIG_DIR=outputs/ultralytics MPLCONFIGDIR=outputs/matplotlib \
.venv/bin/python detect_drone.py \
  --source "provided_data/Air-to-Air 2/Chase_Video.mp4" \
  --model "provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx" \
  --confidence 0.45 \
  --confirm-frames 2 \
  --max-jump-pixels 240 \
  --reacquire-confidence 0.20 \
  --iou-threshold 0.45 \
  --max-detections 20 \
  --onnx-provider coreml \
  --no-preview \
  --save-output \
  --output outputs/chase_filtered_annotated.mp4 \
  --csv-log outputs/chase_filtered.csv
```

## Run All Provided Videos

```bash
TMPDIR=/private/tmp YOLO_CONFIG_DIR=outputs/ultralytics MPLCONFIGDIR=outputs/matplotlib \
.venv/bin/python detect_drone.py \
  --source "provided_data/Air-to-Air 2/Chase_Video.mp4" \
           "provided_data/Air-to-Air 2/DJI_Snow.MP4" \
           "provided_data/Air-to-Air/Video_8min.mp4" \
           "provided_data/drive-download-20260528T184848Z-3-001/Air-to-Air/Vibrations.mp4" \
           "provided_data/drive-download-20260528T184848Z-3-001/Air-to-Air/Vibrations2.mp4" \
  --model "provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx" \
  --confidence 0.35 \
  --detection-interval 1 \
  --reacquire-confidence 0.20 \
  --iou-threshold 0.45 \
  --max-detections 20 \
  --max-missing 6 \
  --prediction-decay 0.85 \
  --max-prediction-frames 4 \
  --imgsz 640 \
  --onnx-provider coreml \
  --no-preview \
  --csv-log outputs/coreml_all_video_logs
```

## Webcam Or Stream

These are supported through OpenCV if the source opens correctly:

```bash
.venv/bin/python detect_drone.py \
  --source 0 \
  --model "provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx" \
  --onnx-provider coreml \
  --realtime
```

```bash
.venv/bin/python detect_drone.py \
  --source rtsp://user:pass@host/stream \
  --model "provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx" \
  --onnx-provider coreml \
  --realtime
```

Live camera/RTSP has not been tuned as much as file playback.

## Important CLI Flags

```text
--source                 video file(s), camera index, stream URL, or video directory
--model                  .onnx or .pt model path
--confidence             detector threshold
--target-class           label to keep, default drone
--allow-any-class        disable class filtering
--save-output            write annotated MP4
--output                 output file or output directory
--csv-log                CSV file or CSV output directory
--no-preview             do not open OpenCV window
--realtime               pace preview to source FPS
--drop-late-frames       skip ahead if preview falls behind
--async-detection        run detection in a worker thread
--detection-interval     run detector every N frames
--smoothing-alpha        marker smoothing factor
--max-missing            keep marker for N missed detection cycles
--confirm-frames         require N consistent hits before showing new target
--max-jump-pixels        reject large jumps unless they persist
--reacquire-confidence   lower threshold only for continuing an existing nearby target
--iou-threshold          NMS overlap threshold for duplicate boxes
--max-detections         maximum boxes kept per frame after postprocessing
--no-predict-missing-motion
                         disable motion extrapolation through detector misses
--prediction-decay       velocity decay per missed frame while predicting
--max-prediction-frames  stop extrapolating after N missed frames
--low-confidence         below this, draw low-confidence style
--imgsz                  model input size
--device                 Ultralytics/PyTorch device for .pt models
--onnx-provider          auto, coreml, cpu, or ultralytics for .onnx models
```

## Choosing Settings

For best live feel on this Mac:

```text
--onnx-provider coreml
--detection-interval 1
--realtime
```

For fewer false positives:

```text
--confidence 0.45 to 0.60
--reacquire-confidence 0.20 to 0.30
--confirm-frames 2
--max-jump-pixels 200 to 300
--iou-threshold 0.45
--max-detections 10 to 20
--prediction-decay 0.80 to 0.90
--max-prediction-frames 3 to 6
```

For more sensitive detection:

```text
--confidence 0.25 to 0.35
--reacquire-confidence 0.15 to 0.25
--confirm-frames 1
--max-detections 20
```

That will find more candidates but will also create more false positives.
