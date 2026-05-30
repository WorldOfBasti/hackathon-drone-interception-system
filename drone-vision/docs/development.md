# Development Notes

## Test Suite

Run:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

At the time of this documentation, the suite has 47 tests covering:

- CLI parsing and directory source expansion.
- COCO-to-YOLO conversion.
- Detection result selection, stable target selection, NMS, and ONNX single-class score handling.
- Circle calculation.
- CSV row formatting.
- Tracker smoothing, missing-frame persistence, prediction, target confirmation, and jump rejection.
- Pipeline behavior when a far high-confidence false positive competes with a nearby target.
- Pipeline behavior for weak nearby reacquisition and weak far-away rejection.
- Preview controls and realtime wait calculation.
- Basic video pipeline with fake OpenCV.
- Input validation.

## Syntax Check

```bash
.venv/bin/python -m compileall drone_overlay tools detect_drone.py tests
```

## Project Style

- Keep runtime dependencies lazy where possible.
- Core math and tracking should remain testable without OpenCV or Ultralytics.
- Use `apply_patch` for manual edits.
- Keep generated data out of source control.
- Add a regression test whenever fixing a bug.

## Adding A Detector Backend

Implement the `Detector` protocol:

```python
class Detector(Protocol):
    def predict(self, frame: Any, *, confidence: float) -> list[Detection]:
        ...
```

Return detections in pixel coordinates:

```python
Detection(
    box=BoundingBox(x1, y1, x2, y2),
    confidence=0.82,
    label="drone",
    class_id=0,
)
```

Wire it through `create_detector()` in `drone_overlay/detection.py`.

## Adding Tracking

The current tracker is intentionally simple. If replacing it with ByteTrack, BoT-SORT, optical flow, or Kalman filtering:

- Keep `CircleMarker` as the overlay contract.
- Keep no-detection behavior explicit.
- Add tests for target persistence, target loss, target switching, and false-positive rejection.
- Avoid blocking the preview loop.

## Generated Files

Common generated paths:

```text
outputs/
datasets/
runs/
.venv/
```

The repository currently includes local data in the working directory, but these should be treated as machine-local artifacts, not source files.

## Useful One-Off Commands

Inspect ONNX providers:

```bash
.venv/bin/python - <<'PY'
import onnxruntime as ort
print(ort.__version__)
print(ort.get_available_providers())
PY
```

Inspect provided ONNX metadata:

```bash
.venv/bin/python - <<'PY'
import onnx
model = onnx.load("provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx")
print([(i.name, [d.dim_value or d.dim_param for d in i.type.tensor_type.shape.dim]) for i in model.graph.input])
print([(o.name, [d.dim_value or d.dim_param for d in o.type.tensor_type.shape.dim]) for o in model.graph.output])
print({p.key: p.value for p in model.metadata_props if p.key in {"task", "names", "imgsz"}})
PY
```

Summarize CSV logs:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import csv

for path in sorted(Path("outputs/coreml_all_video_logs").glob("*.csv")):
    rows = 0
    detected = 0
    conf = []
    lat = []
    for row in csv.DictReader(path.open(newline="", encoding="utf-8")):
        rows += 1
        if row["latency_ms"]:
            lat.append(float(row["latency_ms"]))
        if row["detected"] == "1":
            detected += 1
            if row["confidence"]:
                conf.append(float(row["confidence"]))
    print(path.name, rows, detected, sum(conf) / len(conf) if conf else 0, sum(lat) / len(lat) if lat else 0)
PY
```

## Release Checklist For A Demo

1. Confirm the ONNX model loads with CoreML.
2. Run the live preview on `Chase_Video.mp4`.
3. Generate at least one annotated MP4 for backup.
4. Run headless logs on all videos.
5. Sample false positives and missed detections.
6. Decide final demo settings for confidence and tracker filters.
7. Keep the command in a shell script if multiple people need to run it.
