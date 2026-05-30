"""MOG2 → ROI extraction → YOLO confirmation pipeline.

Owns the MOG2 background subtractor and the YOLO ONNX detector.
Returns MtiResult per frame with mask, ROIs, and confirmed detections.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from mti_detector.bg_subtraction import BackgroundSubtractor

from drone_overlay.detection import BoundingBox, Detection, OnnxRuntimeYoloDetector


@dataclass
class MtiResult:
    """Result of one MtiGuidedDetector.process_frame() call.

    Attributes
    ----------
    fg_mask : np.ndarray | None
        Cleaned binary foreground mask (0 or 255). None during warmup
        before first apply() return is captured.
    rois : list[BoundingBox]
        Moving region bounding boxes in full-frame pixel coordinates.
    detections : list[Detection]
        YOLO-confirmed drone detections (all from ROIs or full-frame).
    detection_source : str
        "warmup", "mti", or "full_frame_fallback".
    frame_count : int
        Total frames processed so far (1-indexed).
    processing_ms : float
        Total processing time for this frame in milliseconds.
    """

    fg_mask: np.ndarray | None = None
    rois: list[BoundingBox] = field(default_factory=list)
    detections: list[Detection] = field(default_factory=list)
    detection_source: str = "mti"
    frame_count: int = 0
    processing_ms: float = 0.0


class MtiGuidedDetector:
    """Orchestrates MOG2 background subtraction → ROI extraction → YOLO detection.

    Parameters
    ----------
    model_path : str
        Path to the YOLO .onnx model file.
    onnx_provider : str
        ONNX Runtime provider. "coreml" for Apple Silicon, "cpu" otherwise.
        Default "coreml".
    confidence : float
        YOLO detection confidence threshold. Default 0.35.
    bgsubtractor : BackgroundSubtractor | None
        Optional pre-configured MOG2 subtractor. Created with defaults if None.
    warmup_frames : int
        Number of initial frames where MOG2 builds its model silently while
        YOLO runs on full frames. Default 100.
    min_contour_area : int
        Minimum contour area (pixels) to consider as a moving region.
        Filters out compression noise. Default 50.
    max_rois : int
        Maximum number of ROIs to process per frame (sorted by contour area).
        Default 5.
    roi_padding_ratio : float
        Fraction of ROI dimensions to add as padding for YOLO context.
        Default 0.3 (30%).
    min_roi_dim : int
        Minimum padded ROI dimension in pixels. Ensures YOLO has enough
        image context to classify. Default 64.
    iou_merge_threshold : float
        IoU threshold for merging overlapping ROIs before padding.
        Default 0.3.
    """

    def __init__(
        self,
        model_path: str,
        *,
        onnx_provider: str = "coreml",
        confidence: float = 0.35,
        bgsubtractor: BackgroundSubtractor | None = None,
        warmup_frames: int = 100,
        min_contour_area: int = 50,
        max_rois: int = 5,
        roi_padding_ratio: float = 0.3,
        min_roi_dim: int = 64,
        iou_merge_threshold: float = 0.3,
    ) -> None:
        self._model_path = model_path
        self._onnx_provider = onnx_provider
        self._confidence = confidence
        self._warmup_frames = warmup_frames
        self._min_contour_area = min_contour_area
        self._max_rois = max_rois
        self._roi_padding_ratio = roi_padding_ratio
        self._min_roi_dim = min_roi_dim
        self._iou_merge_threshold = iou_merge_threshold

        self._bg = bgsubtractor or BackgroundSubtractor()
        self._frame_count = 0
        self._yolo: OnnxRuntimeYoloDetector | None = None

    def _ensure_yolo(self) -> OnnxRuntimeYoloDetector:
        if self._yolo is None:
            self._yolo = OnnxRuntimeYoloDetector(
                self._model_path,
                target_class="drone",
                allow_any_class=False,
                provider=self._onnx_provider,
            )
        return self._yolo

    def process_frame(self, frame: np.ndarray, *, confidence: float | None = None) -> MtiResult:
        """Process a single BGR frame through the MOG2 → ROI → YOLO pipeline.

        Parameters
        ----------
        frame : np.ndarray
            BGR image in OpenCV format (H, W, 3).
        confidence : float | None
            Override the default YOLO confidence threshold for this frame.

        Returns
        -------
        MtiResult
        """
        started = time.perf_counter()
        self._frame_count += 1
        yolo_conf = confidence if confidence is not None else self._confidence

        fg_mask = self._bg.apply(frame)

        if self._frame_count <= self._warmup_frames:
            detections = self._full_frame_detect(frame, yolo_conf)
            elapsed = (time.perf_counter() - started) * 1000
            return MtiResult(
                fg_mask=fg_mask,
                rois=[],
                detections=detections,
                detection_source="warmup",
                frame_count=self._frame_count,
                processing_ms=elapsed,
            )

        rois = self._extract_rois(fg_mask, frame.shape)

        if not rois:
            detections = self._full_frame_detect(frame, yolo_conf)
            elapsed = (time.perf_counter() - started) * 1000
            return MtiResult(
                fg_mask=fg_mask,
                rois=[],
                detections=detections,
                detection_source="full_frame_fallback",
                frame_count=self._frame_count,
                processing_ms=elapsed,
            )

        detections = self._detect_in_rois(frame, rois, yolo_conf)
        elapsed = (time.perf_counter() - started) * 1000
        return MtiResult(
            fg_mask=fg_mask,
            rois=rois,
            detections=detections,
            detection_source="mti",
            frame_count=self._frame_count,
            processing_ms=elapsed,
        )

    def reset(self) -> None:
        """Reset the MOG2 background model and frame counter."""
        self._bg.reset()
        self._frame_count = 0

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def is_warm(self) -> bool:
        return self._frame_count > self._warmup_frames

    @property
    def bg_subtractor(self) -> BackgroundSubtractor:
        return self._bg

    @property
    def yolo_detector(self) -> OnnxRuntimeYoloDetector:
        return self._ensure_yolo()

    @property
    def confidence(self) -> float:
        return self._confidence

    @confidence.setter
    def confidence(self, value: float) -> None:
        self._confidence = value

    @property
    def var_threshold(self) -> int:
        return self._bg.var_threshold

    @var_threshold.setter
    def var_threshold(self, value: int) -> None:
        self._bg.var_threshold = value

    def _detect_in_rois(
        self, frame: np.ndarray, rois: list[BoundingBox], confidence: float
    ) -> list[Detection]:
        detections: list[Detection] = []
        yolo = self._ensure_yolo()

        for roi in rois:
            x1 = max(0, int(roi.x1))
            y1 = max(0, int(roi.y1))
            x2 = min(frame.shape[1], int(roi.x2))
            y2 = min(frame.shape[0], int(roi.y2))
            if x2 <= x1 or y2 <= y1:
                continue

            crop = frame[y1:y2, x1:x2]
            crop_dets = yolo.predict(crop, confidence=confidence)
            for d in crop_dets:
                detections.append(
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

        return detections

    def _full_frame_detect(self, frame: np.ndarray, confidence: float) -> list[Detection]:
        yolo = self._ensure_yolo()
        return yolo.predict(frame, confidence=confidence)

    def _extract_rois(self, fg_mask: np.ndarray, frame_shape: tuple) -> list[BoundingBox]:
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return []

        rects = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < self._min_contour_area:
                continue
            x, y, w, h = cv2.boundingRect(c)
            rects.append((x, y, w, h, area))

        rects.sort(key=lambda r: r[4], reverse=True)
        rects = rects[: self._max_rois]

        boxes = [BoundingBox(float(x), float(y), float(x + w), float(y + h)) for x, y, w, h, _ in rects]
        merged = self._merge_overlapping(boxes)
        padded = [self._pad_roi(box, frame_shape) for box in merged]

        return padded

    def _merge_overlapping(self, boxes: list[BoundingBox]) -> list[BoundingBox]:
        if len(boxes) <= 1:
            return list(boxes)

        kept: list[BoundingBox] = []
        for box in boxes:
            merged = False
            for i, existing in enumerate(kept):
                if self._box_iou(box, existing) >= self._iou_merge_threshold:
                    kept[i] = BoundingBox(
                        min(box.x1, existing.x1),
                        min(box.y1, existing.y1),
                        max(box.x2, existing.x2),
                        max(box.y2, existing.y2),
                    )
                    merged = True
                    break
            if not merged:
                kept.append(box)

        return kept

    def _pad_roi(self, box: BoundingBox, frame_shape: tuple) -> BoundingBox:
        h, w = frame_shape[:2]
        roi_w = box.width
        roi_h = box.height

        pad_w = int(roi_w * self._roi_padding_ratio)
        pad_h = int(roi_h * self._roi_padding_ratio)

        target_w = max(int(roi_w + 2 * pad_w), self._min_roi_dim)
        target_h = max(int(roi_h + 2 * pad_h), self._min_roi_dim)

        delta_w = target_w - roi_w
        delta_h = target_h - roi_h

        cx = (box.x1 + box.x2) / 2
        cy = (box.y1 + box.y2) / 2

        x1 = max(0, cx - target_w / 2)
        y1 = max(0, cy - target_h / 2)
        x2 = min(w, cx + target_w / 2)
        y2 = min(h, cy + target_h / 2)

        return BoundingBox(float(x1), float(y1), float(x2), float(y2))

    @staticmethod
    def _box_iou(a: BoundingBox, b: BoundingBox) -> float:
        x1 = max(a.x1, b.x1)
        y1 = max(a.y1, b.y1)
        x2 = min(a.x2, b.x2)
        y2 = min(a.y2, b.y2)
        inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        if inter <= 0:
            return 0.0
        area_a = a.width * a.height
        area_b = b.width * b.height
        return inter / (area_a + area_b - inter)
