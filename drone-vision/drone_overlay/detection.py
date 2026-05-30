"""Detector abstractions and Ultralytics YOLO adapter."""

from __future__ import annotations

import os
from dataclasses import dataclass
from math import hypot
from pathlib import Path
from typing import Any, Iterable, Protocol

from drone_overlay.geometry import BoundingBox, CircleMarker


@dataclass(frozen=True)
class Detection:
    """Single detector result in pixel coordinates."""

    box: BoundingBox
    confidence: float
    label: str = "drone"
    class_id: int | None = None


class Detector(Protocol):
    """Frame detector interface used by the video processor."""

    def predict(self, frame: Any, *, confidence: float) -> list[Detection]:
        """Return detections for a BGR frame."""


def create_detector(
    model_path: str | Path,
    *,
    target_class: str | None = "drone",
    allow_any_class: bool = False,
    imgsz: int | None = None,
    device: str | None = None,
    onnx_provider: str = "auto",
    iou_threshold: float = 0.45,
    max_detections: int = 20,
    use_wbf: bool = True,
    enable_fp_filter: bool = True,
) -> Detector:
    """Create the fastest supported detector for the requested model/runtime."""

    path = Path(model_path)
    if path.suffix.lower() == ".onnx" and onnx_provider != "ultralytics":
        return OnnxRuntimeYoloDetector(
            path,
            target_class=target_class,
            allow_any_class=allow_any_class,
            imgsz=imgsz or 640,
            provider=onnx_provider,
            iou_threshold=iou_threshold,
            max_detections=max_detections,
            use_wbf=use_wbf,
            enable_fp_filter=enable_fp_filter,
        )

    return YoloDetector(
        path,
        target_class=target_class,
        allow_any_class=allow_any_class,
        imgsz=imgsz,
        device=device,
        iou_threshold=iou_threshold,
        max_detections=max_detections,
    )


def select_best_detection(detections: Iterable[Detection]) -> Detection | None:
    """Pick the highest-confidence detection from an iterable."""

    return max(detections, key=lambda detection: detection.confidence, default=None)


def select_stable_detection(
    detections: Iterable[Detection],
    *,
    current_marker: CircleMarker | None = None,
    max_jump_pixels: float | None = None,
    min_new_target_confidence: float = 0.0,
) -> Detection | None:
    """Prefer the strongest plausible continuation of the current target."""

    if not 0 <= min_new_target_confidence <= 1:
        raise ValueError("min_new_target_confidence must be in the range [0, 1]")

    candidates = list(detections)
    if current_marker is None or max_jump_pixels is None:
        return select_best_detection(
            detection
            for detection in candidates
            if detection.confidence >= min_new_target_confidence
        )

    nearby = [
        detection
        for detection in candidates
        if _center_distance(detection, current_marker) <= max_jump_pixels
    ]
    if nearby:
        return select_best_detection(nearby)

    return select_best_detection(
        detection
        for detection in candidates
        if detection.confidence >= min_new_target_confidence
    )


def non_max_suppression(
    detections: Iterable[Detection],
    *,
    iou_threshold: float = 0.45,
    max_detections: int = 20,
) -> list[Detection]:
    """Suppress duplicate overlapping boxes while preserving confidence order."""

    if not 0 <= iou_threshold <= 1:
        raise ValueError("iou_threshold must be in the range [0, 1]")
    if max_detections < 1:
        raise ValueError("max_detections must be at least 1")

    kept: list[Detection] = []
    for detection in sorted(detections, key=lambda candidate: candidate.confidence, reverse=True):
        if len(kept) >= max_detections:
            break
        if all(
            not _same_nms_class(detection, accepted)
            or _box_iou(detection.box, accepted.box) <= iou_threshold
            for accepted in kept
        ):
            kept.append(detection)
    return kept


class OnnxRuntimeYoloDetector:
    """Small YOLO ONNX Runtime adapter with optional CoreML execution provider."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        target_class: str | None = "drone",
        allow_any_class: bool = False,
        imgsz: int = 640,
        provider: str = "auto",
        iou_threshold: float = 0.45,
        max_detections: int = 20,
        use_wbf: bool = True,
        enable_fp_filter: bool = True,
    ) -> None:
        self.model_path = Path(model_path)
        self.target_class = target_class.strip().lower() if target_class else None
        self.allow_any_class = allow_any_class
        self.imgsz = imgsz
        self.provider = provider
        self.iou_threshold = iou_threshold
        self.max_detections = max_detections
        self.use_wbf = use_wbf
        self.enable_fp_filter = enable_fp_filter

        if not 0 <= self.iou_threshold <= 1:
            raise ValueError("iou_threshold must be in the range [0, 1]")
        if self.max_detections < 1:
            raise ValueError("max_detections must be at least 1")

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found: {self.model_path}")

        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError(
                "onnxruntime is not installed. Install it with "
                "`python -m pip install onnxruntime onnx`."
            ) from exc

        self.ort = ort

        session_opts = ort.SessionOptions()
        session_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        session_opts.enable_mem_pattern = True
        session_opts.intra_op_num_threads = min(8, os.cpu_count() or 4)
        session_opts.inter_op_num_threads = 1
        session_opts.add_session_config_entry("session.intra_op.allow_spinning", "0")

        self.session = ort.InferenceSession(
            str(self.model_path),
            sess_options=session_opts,
            providers=self._providers(provider),
        )
        self.input_name = self.session.get_inputs()[0].name
        input_shape = self.session.get_inputs()[0].shape
        if input_shape and len(input_shape) >= 4:
            model_h = input_shape[2]
            if isinstance(model_h, int) and model_h > 0:
                self.imgsz = model_h
        self.names = self._metadata_names()

    def predict(self, frame: Any, *, confidence: float) -> list[Detection]:
        blob, scale, pad_x, pad_y = self._preprocess(frame)
        outputs = self.session.run(None, {self.input_name: blob})
        predictions = outputs[0]
        if predictions.ndim == 3:
            predictions = predictions[0]
        if predictions.shape[0] <= predictions.shape[1]:
            predictions = predictions.T

        detections: list[Detection] = []
        frame_height, frame_width = frame.shape[:2]
        for row in predictions:
            if row.shape[0] < 5:
                continue

            class_id, score = self._class_and_score(row)
            if score < confidence:
                continue

            label = self.names.get(class_id, str(class_id))
            if not self._class_allowed(label):
                continue

            x_center, y_center, width, height = [float(value) for value in row[:4]]
            x1 = (x_center - width / 2 - pad_x) / scale
            y1 = (y_center - height / 2 - pad_y) / scale
            x2 = (x_center + width / 2 - pad_x) / scale
            y2 = (y_center + height / 2 - pad_y) / scale
            x1 = max(0.0, min(float(frame_width - 1), x1))
            y1 = max(0.0, min(float(frame_height - 1), y1))
            x2 = max(0.0, min(float(frame_width - 1), x2))
            y2 = max(0.0, min(float(frame_height - 1), y2))
            if x2 <= x1 or y2 <= y1:
                continue

            detections.append(
                Detection(
                    box=BoundingBox(x1, y1, x2, y2),
                    confidence=score,
                    label=label,
                    class_id=class_id,
                )
            )

        if self.use_wbf:
            detections = _wbf_fusion(
                detections,
                frame_width,
                frame_height,
                self.names,
                iou_thr=self.iou_threshold,
            )
        else:
            detections = non_max_suppression(
                detections,
                iou_threshold=self.iou_threshold,
                max_detections=self.max_detections,
            )

        if self.enable_fp_filter:
            detections = filter_false_positives(
                detections, frame_width=frame_width, frame_height=frame_height
            )

        return detections[: self.max_detections]

    @property
    def providers(self) -> list[str]:
        return list(self.session.get_providers())

    def _providers(self, provider: str):
        available = set(self.ort.get_available_providers())
        if provider == "cpu":
            return ["CPUExecutionProvider"]
        if provider == "coreml":
            if "CoreMLExecutionProvider" not in available:
                raise RuntimeError(
                    "CoreMLExecutionProvider is not available in this onnxruntime build."
                )
            return [self._coreml_provider_options(), "CPUExecutionProvider"]
        if provider == "directml":
            if "DmlExecutionProvider" in available:
                return ["DmlExecutionProvider", "CPUExecutionProvider"]
            raise RuntimeError(
                "DmlExecutionProvider is not available. Install onnxruntime-directml."
            )
        if provider == "auto":
            if "CoreMLExecutionProvider" in available:
                return [self._coreml_provider_options(), "CPUExecutionProvider"]
            if "DmlExecutionProvider" in available:
                return ["DmlExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    def _coreml_provider_options(self):
        return (
            "CoreMLExecutionProvider",
            {
                "ModelFormat": "MLProgram",
                "MLComputeUnits": "ALL",
                "RequireStaticInputShapes": "1",
                "EnableOnSubgraphs": "0",
                "ModelCacheDirectory": str(Path("outputs/coreml_cache").resolve()),
            },
        )

    def _metadata_names(self) -> dict[int, str]:
        import ast

        metadata = self.session.get_modelmeta().custom_metadata_map
        raw_names = metadata.get("names")
        if raw_names:
            try:
                parsed = ast.literal_eval(raw_names)
                if isinstance(parsed, dict):
                    return {int(key): str(value) for key, value in parsed.items()}
            except (ValueError, SyntaxError):
                pass
        return {0: self.target_class or "0"}

    def _class_allowed(self, label: str) -> bool:
        if self.allow_any_class or self.target_class is None:
            return True
        return label.strip().lower() == self.target_class

    def _class_and_score(self, row) -> tuple[int, float]:
        if row.shape[0] == 5:
            return 0, float(row[4])
        class_scores = row[4:]
        class_id = int(class_scores.argmax())
        return class_id, float(class_scores[class_id])

    def _preprocess(self, frame: Any):
        import cv2
        import numpy as np

        height, width = frame.shape[:2]
        scale = min(self.imgsz / width, self.imgsz / height)
        resized_width = round(width * scale)
        resized_height = round(height * scale)
        resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
        pad_x = (self.imgsz - resized_width) / 2
        pad_y = (self.imgsz - resized_height) / 2

        canvas = np.full((self.imgsz, self.imgsz, 3), 114, dtype=np.uint8)
        left = int(round(pad_x - 0.1))
        top = int(round(pad_y - 0.1))
        canvas[top : top + resized_height, left : left + resized_width] = resized
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        blob = rgb.transpose(2, 0, 1)[None].astype("float32") / 255.0
        return blob, scale, left, top


class YoloDetector:
    """Ultralytics YOLO detector loaded lazily so tests do not need ML dependencies."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        target_class: str | None = "drone",
        allow_any_class: bool = False,
        imgsz: int | None = None,
        device: str | None = None,
        iou_threshold: float = 0.45,
        max_detections: int = 20,
    ) -> None:
        self.model_path = Path(model_path)
        self.target_class = target_class.strip().lower() if target_class else None
        self.allow_any_class = allow_any_class
        self.imgsz = imgsz
        self.device = device
        self.iou_threshold = iou_threshold
        self.max_detections = max_detections

        if not 0 <= self.iou_threshold <= 1:
            raise ValueError("iou_threshold must be in the range [0, 1]")
        if self.max_detections < 1:
            raise ValueError("max_detections must be at least 1")

        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "Ultralytics is not installed. Install dependencies with "
                "`python -m pip install -r requirements.txt`."
            ) from exc

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found: {self.model_path}")

        self.model = YOLO(str(self.model_path), task="detect")
        self.names = self._normalize_names(getattr(self.model, "names", {}))

    def predict(self, frame: Any, *, confidence: float) -> list[Detection]:
        kwargs: dict[str, Any] = {
            "conf": confidence,
            "iou": self.iou_threshold,
            "max_det": self.max_detections,
            "verbose": False,
        }
        if self.imgsz:
            kwargs["imgsz"] = self.imgsz
        if self.device:
            kwargs["device"] = self.device

        results = self.model.predict(frame, **kwargs)
        detections: list[Detection] = []

        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue

            for raw_box in boxes:
                class_id = self._to_int(raw_box.cls)
                label = self.names.get(class_id, str(class_id))
                if not self._class_allowed(label):
                    continue

                xyxy = raw_box.xyxy[0]
                coords = [self._to_float(value) for value in xyxy]
                detections.append(
                    Detection(
                        box=BoundingBox(*coords),
                        confidence=self._to_float(raw_box.conf),
                        label=label,
                        class_id=class_id,
                    )
                )

        return detections

    def _class_allowed(self, label: str) -> bool:
        if self.allow_any_class or self.target_class is None:
            return True
        return label.strip().lower() == self.target_class

    @staticmethod
    def _normalize_names(names: Any) -> dict[int, str]:
        if isinstance(names, dict):
            return {int(key): str(value) for key, value in names.items()}
        if isinstance(names, list):
            return {index: str(value) for index, value in enumerate(names)}
        return {}

    @staticmethod
    def _to_float(value: Any) -> float:
        if hasattr(value, "item"):
            return float(value.item())
        return float(value)

    @classmethod
    def _to_int(cls, value: Any) -> int:
        return int(cls._to_float(value))


class SahiDetector:
    """SAHI (Slicing Aided Hyper Inference) — tiles frame into overlapping slices
    for better small-object recall, then merges tile detections via WBF."""

    def __init__(
        self,
        base_detector: Detector,
        *,
        tile_size: int = 320,
        overlap: float = 0.2,
    ) -> None:
        self.base_detector = base_detector
        self.tile_size = tile_size
        self.overlap = overlap

    def predict(self, frame: Any, *, confidence: float) -> list[Detection]:
        import cv2

        h, w = frame.shape[:2]
        stride = max(1, int(self.tile_size * (1.0 - self.overlap)))

        all_detections: list[Detection] = []

        for y in range(0, h, stride):
            for x in range(0, w, stride):
                x2 = min(x + self.tile_size, w)
                y2 = min(y + self.tile_size, h)
                x1 = max(0, x2 - self.tile_size)
                y1 = max(0, y2 - self.tile_size)
                if x2 <= x1 or y2 <= y1:
                    continue

                tile = frame[y1:y2, x1:x2]
                tile_detections = self.base_detector.predict(tile, confidence=confidence)

                for d in tile_detections:
                    all_detections.append(
                        Detection(
                            box=BoundingBox(
                                d.box.x1 + x1,
                                d.box.y1 + y1,
                                d.box.x2 + x1,
                                d.box.y2 + y1,
                            ),
                            confidence=d.confidence,
                            label=d.label,
                            class_id=d.class_id,
                        )
                    )

        return _wbf_fusion(all_detections, w, h, {}, iou_thr=0.5)


class TtaDetector:
    """Test-Time Augmentation — runs multi-scale + horizontal flip inference,
    then merges all results via WBF for maximum recall."""

    def __init__(
        self,
        base_detector_constructor: Any,
        *,
        model_path: str | Path,
        target_class: str | None,
        allow_any_class: bool,
        iou_threshold: float,
        max_detections: int,
        provider: str,
        scales: tuple[int, ...] = (640, 960),
        use_wbf: bool = True,
        enable_fp_filter: bool = True,
    ) -> None:
        self._ctor = base_detector_constructor
        self._model_path = model_path
        self._target_class = target_class
        self._allow_any_class = allow_any_class
        self._iou_threshold = iou_threshold
        self._max_detections = max_detections
        self._provider = provider
        self._scales = scales
        self._use_wbf = use_wbf
        self._enable_fp_filter = enable_fp_filter

    def predict(self, frame: Any, *, confidence: float) -> list[Detection]:
        import cv2

        h, w = frame.shape[:2]
        all_detections: list[Detection] = []

        for imgsz in self._scales:
            detector = self._ctor(
                self._model_path,
                target_class=self._target_class,
                allow_any_class=self._allow_any_class,
                imgsz=imgsz,
                provider=self._provider,
                iou_threshold=self._iou_threshold,
                max_detections=self._max_detections,
                use_wbf=self._use_wbf,
                enable_fp_filter=self._enable_fp_filter,
            )

            for flipped in (False, True):
                input_frame = cv2.flip(frame, 1) if flipped else frame
                dets = detector.predict(input_frame, confidence=confidence)
                for d in dets:
                    if flipped:
                        flipped_x1 = w - d.box.x2
                        flipped_x2 = w - d.box.x1
                        all_detections.append(
                            Detection(
                                box=BoundingBox(flipped_x1, d.box.y1, flipped_x2, d.box.y2),
                                confidence=d.confidence,
                                label=d.label,
                                class_id=d.class_id,
                            )
                        )
                    else:
                        all_detections.append(d)

        return _wbf_fusion(all_detections, w, h, {}, iou_thr=0.5)


def _center_distance(detection: Detection, marker: CircleMarker) -> float:
    return hypot(detection.box.center_x - marker.center_x, detection.box.center_y - marker.center_y)


def _box_iou(first: BoundingBox, second: BoundingBox) -> float:
    x1 = max(first.x1, second.x1)
    y1 = max(first.y1, second.y1)
    x2 = min(first.x2, second.x2)
    y2 = min(first.y2, second.y2)
    intersection_width = max(0.0, x2 - x1)
    intersection_height = max(0.0, y2 - y1)
    intersection = intersection_width * intersection_height
    if intersection <= 0:
        return 0.0

    first_area = first.width * first.height
    second_area = second.width * second.height
    union = first_area + second_area - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _same_nms_class(first: Detection, second: Detection) -> bool:
    if first.class_id is not None and second.class_id is not None:
        return first.class_id == second.class_id
    return first.label == second.label


def _wbf_fusion(
    detections: list[Detection],
    frame_width: int,
    frame_height: int,
    names: dict,
    *,
    iou_thr: float = 0.55,
) -> list[Detection]:
    """Weighted Boxes Fusion — replaces NMS with confidence-weighted box averaging."""
    if len(detections) <= 1:
        return list(detections)

    try:
        from ensemble_boxes import weighted_boxes_fusion
        import numpy as np
    except ImportError:
        return non_max_suppression(detections, iou_threshold=iou_thr)

    boxes_norm = []
    scores = []
    labels_int = []
    for d in detections:
        boxes_norm.append([
            d.box.x1 / frame_width,
            d.box.y1 / frame_height,
            d.box.x2 / frame_width,
            d.box.y2 / frame_height,
        ])
        scores.append(d.confidence)
        labels_int.append(d.class_id if d.class_id is not None else 0)

    if not boxes_norm:
        return []

    merged_boxes, merged_scores, merged_labels = weighted_boxes_fusion(
        [np.array(boxes_norm, dtype=np.float64)],
        [np.array(scores, dtype=np.float64)],
        [np.array(labels_int, dtype=np.int32)],
        weights=[1.0],
        iou_thr=iou_thr,
        skip_box_thr=0.0,
    )

    result: list[Detection] = []
    for box, score, label_id in zip(merged_boxes, merged_scores, merged_labels):
        x1 = box[0] * frame_width
        y1 = box[1] * frame_height
        x2 = box[2] * frame_width
        y2 = box[3] * frame_height
        label_name = names.get(int(label_id), str(int(label_id)))
        result.append(
            Detection(
                box=BoundingBox(x1, y1, x2, y2),
                confidence=float(score),
                label=label_name,
                class_id=int(label_id),
            )
        )

    return result


def filter_false_positives(
    detections: list[Detection],
    *,
    min_size: float = 10.0,
    max_aspect_ratio: float = 5.0,
    frame_width: int | None = None,
    frame_height: int | None = None,
) -> list[Detection]:
    """Remove detections with implausible size or aspect ratio."""
    result: list[Detection] = []
    for d in detections:
        w = d.box.width
        h = d.box.height
        if w < min_size or h < min_size:
            continue
        aspect = max(w, h) / max(min(w, h), 1.0)
        if aspect > max_aspect_ratio:
            continue
        result.append(d)
    return result
