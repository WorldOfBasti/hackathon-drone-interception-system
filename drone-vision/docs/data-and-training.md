# Data And Training

## Provided Data

The `provided_data/` folder contains:

```text
Air-to-Air/
  Video_8min.mp4

Air-to-Air 2/
  Chase_Video.mp4
  DJI_Snow.MP4

drive-download-20260528T184848Z-3-001/
  Baseline_yolo11s_Modell.onnx
  Readme.pdf
  Air-to-Air/
    Vibrations.mp4
    Vibrations2.mp4

daedalus-hackaburg.coco-004/
  README.roboflow.txt
  train/_annotations.coco.json
  train/*.jpg

Datasets/
  drone.coco.zip
```

The `compressed/` folder, when present, contains duplicate archives and can be very large.

## Provided Model

Model:

```text
provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx
```

Metadata:

```text
task: detect
names: {0: 'drone'}
input: 1 x 3 x 640 x 640
output: 1 x 5 x 8400
```

This is the current production-ish baseline for the app. It runs well with CoreML.

## Provided COCO Dataset

The large Roboflow export:

```text
provided_data/daedalus-hackaburg.coco-004/train/_annotations.coco.json
```

Observed counts:

```text
59752 images
61401 annotations
0 images without annotations
category_id 1 used for all annotations
active class name: drone
mostly 640 x 480 images
```

There are two category entries in the COCO metadata, but all annotations use the actual `drone` category. The converter collapses class names into one YOLO class.

## Convert COCO To YOLO

Use the converter:

```bash
.venv/bin/python tools/convert_coco_to_yolo.py \
  --source provided_data/daedalus-hackaburg.coco-004/train \
  --output datasets/daedalus-hackaburg-yolo \
  --val-prefix pos_G2 \
  --overwrite
```

The converter:

- Reads `_annotations.coco.json`.
- Converts COCO `x, y, width, height` boxes into YOLO normalized center format.
- Writes `labels/train/*.txt` and `labels/val/*.txt`.
- Creates image symlinks instead of copying images by default.
- Writes `data.yaml`.
- Uses `--val-prefix pos_G2` as a simple source-group validation holdout.

Do not random-split adjacent frames from the same videos if you care about honest validation. That will leak near-duplicates into validation and inflate metrics.

## Smaller Converted Dataset

Earlier conversion of a smaller export produced:

```text
datasets/drone-yolo/data.yaml
10867 train images
1622 val images
12913 annotations
```

This can be used for quick experiments if the 60k dataset is too slow.

## Training Baseline

CPU training works but is slow. MPS is not currently available in this venv.

Example CPU training:

```bash
YOLO_CONFIG_DIR=outputs/ultralytics MPLCONFIGDIR=outputs/matplotlib \
.venv/bin/yolo detect train \
  model=yolo11n.pt \
  data=datasets/daedalus-hackaburg-yolo/data.yaml \
  epochs=50 \
  imgsz=640 \
  batch=8 \
  device=cpu \
  workers=0 \
  project=runs/drone \
  name=yolo11n_640
```

If MPS becomes available in a clean environment:

```bash
device=mps
```

But do not assume it works until this check passes:

```bash
.venv/bin/python - <<'PY'
import torch
print(torch.backends.mps.is_built())
print(torch.backends.mps.is_available())
print(torch.ones(1, device="mps"))
PY
```

## Improving Detection Quality

App-level filters help presentation quality:

```text
--confidence
--reacquire-confidence
--iou-threshold
--max-detections
--confirm-frames
--max-jump-pixels
--max-missing
--prediction-decay
--max-prediction-frames
--smoothing-alpha
```

They do not fix the model. For real detection improvement:

1. Review false positives and false negatives from the five videos.
2. Add hard negatives: birds, snow, artifacts, empty sky, buildings, trees, motion blur.
3. Keep validation split by source/video group.
4. Train a small model first (`yolo11n` or `yolo11s`) before trying larger models.
5. Re-run the overlay app on all provided videos.
6. Compare CSV logs and annotated clips, not just mAP.

## Suggested Evaluation Loop

1. Run current model on all videos with CSV logs.
2. Sample frames where confidence is high but the result is wrong.
3. Sample frames where the drone is visible but undetected.
4. Label/review those in Roboflow.
5. Export a new dataset version.
6. Train.
7. Export to ONNX.
8. Run with `--onnx-provider coreml`.
9. Compare:
   - detected row count,
   - average confidence,
   - false-positive samples,
   - first detection frame,
   - visual stability.

## Disk Space Notes

The extracted 60k dataset is about 7.8 GB. The compressed archives can take much more. At one point `provided_data/compressed` was about 13 GB and was the obvious cleanup target.

Training needs more space than conversion:

```text
COCO -> YOLO symlink conversion: about a few hundred MB
basic local training workspace: 10-15 GB free
comfortable iteration: 25-40 GB free
```
