"""Video processing loop for detection, tracking, overlay, and export."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from drone_overlay.detection import Detector, SahiDetector, TtaDetector, create_detector, select_stable_detection
from drone_overlay.metrics import CsvDetectionLogger, FrameMetrics, RollingFps
from drone_overlay.overlay import OverlayOptions, draw_frame_overlay
from drone_overlay.tracking import SmoothedTargetTracker, TrackerConfig


VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}


@dataclass
class VideoProcessorConfig:
    source: str
    model: str
    confidence: float = 0.35
    target_class: str | None = "drone"
    allow_any_class: bool = False
    save_output: bool = False
    output: str | None = None
    csv_log: str | None = None
    no_preview: bool = False
    show_overlay: bool = True
    show_confidence: bool = True
    realtime: bool = False
    drop_late_frames: bool = False
    async_detection: bool = False
    detection_interval: int = 1
    smoothing_alpha: float = 0.45
    max_missing: int = 8
    circle_padding: float = 12
    min_radius: float = 12
    low_confidence: float = 0.5
    confirm_frames: int = 1
    max_jump_pixels: float | None = None
    reacquire_confidence: float = 0.2
    iou_threshold: float = 0.45
    max_detections: int = 20
    predict_missing_motion: bool = True
    prediction_decay: float = 0.85
    max_prediction_frames: int | None = 4
    imgsz: int | None = None
    device: str | None = None
    onnx_provider: str = "auto"
    use_wbf: bool = True
    enable_fp_filter: bool = True
    use_sahi: bool = False
    sahi_tile_size: int = 320
    sahi_overlap: float = 0.2
    use_tta: bool = False
    tta_scales: tuple[int, ...] = (640, 960)
    enable_preprocess: bool = True
    use_kalman: bool = False
    vote_window: int = 5
    vote_threshold: int = 1


@dataclass(frozen=True)
class ProcessingSummary:
    source: str
    frames_processed: int
    average_fps: float
    output_path: str | None
    csv_log_path: str | None


def process_video(
    config: VideoProcessorConfig,
    detector: Detector | None = None,
) -> ProcessingSummary:
    """Process one video/camera/stream source."""

    if config.detection_interval < 1:
        raise ValueError("detection_interval must be at least 1")
    if not 0 <= config.confidence <= 1:
        raise ValueError("confidence must be in the range [0, 1]")
    if not 0 <= config.reacquire_confidence <= 1:
        raise ValueError("reacquire_confidence must be in the range [0, 1]")
    if not 0 <= config.iou_threshold <= 1:
        raise ValueError("iou_threshold must be in the range [0, 1]")
    if config.max_detections < 1:
        raise ValueError("max_detections must be at least 1")
    if not 0 <= config.prediction_decay <= 1:
        raise ValueError("prediction_decay must be in the range [0, 1]")
    if config.max_prediction_frames is not None and config.max_prediction_frames < 0:
        raise ValueError("max_prediction_frames must be non-negative when set")

    source = _parse_source(config.source)
    _validate_local_video_source(config.source)
    cv2 = _load_cv2()

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video source: {config.source}")

    detector = detector or create_detector(
        config.model,
        target_class=config.target_class,
        allow_any_class=config.allow_any_class,
        imgsz=config.imgsz,
        device=config.device,
        onnx_provider=config.onnx_provider,
        iou_threshold=config.iou_threshold,
        max_detections=config.max_detections,
        use_wbf=config.use_wbf,
        enable_fp_filter=config.enable_fp_filter,
    )

    if config.use_tta:
        from drone_overlay.detection import OnnxRuntimeYoloDetector

        detector = TtaDetector(
            OnnxRuntimeYoloDetector,
            model_path=config.model,
            target_class=config.target_class,
            allow_any_class=config.allow_any_class,
            iou_threshold=config.iou_threshold,
            max_detections=config.max_detections,
            provider=config.onnx_provider,
            scales=config.tta_scales,
            use_wbf=config.use_wbf,
            enable_fp_filter=config.enable_fp_filter,
        )

    if config.use_sahi:
        detector = SahiDetector(
            detector,
            tile_size=config.sahi_tile_size,
            overlap=config.sahi_overlap,
        )

    tracker = SmoothedTargetTracker(
        TrackerConfig(
            smoothing_alpha=config.smoothing_alpha,
            max_missing=config.max_missing,
            circle_padding=config.circle_padding,
            min_radius=config.min_radius,
            low_confidence_threshold=config.low_confidence,
            confirm_frames=config.confirm_frames,
            max_jump_pixels=config.max_jump_pixels,
            predict_missing_motion=config.predict_missing_motion,
            prediction_decay=config.prediction_decay,
            max_prediction_frames=config.max_prediction_frames,
            use_kalman=config.use_kalman,
            vote_window=config.vote_window,
            vote_threshold=config.vote_threshold,
        )
    )

    source_name = _source_name(config.source)
    output_path = _resolve_output_path(config) if config.save_output else None
    csv_path = Path(config.csv_log) if config.csv_log else None
    logger = CsvDetectionLogger(csv_path) if csv_path else None

    writer = None
    source_fps = cap.get(cv2.CAP_PROP_FPS) or 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fps_for_output = source_fps if source_fps > 0 else 30
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(output_path), fourcc, fps_for_output, (width, height))
        if not writer.isOpened():
            cap.release()
            if logger:
                logger.close()
            raise RuntimeError(f"Could not open output video for writing: {output_path}")

    frame_number = 0
    fps_counter = RollingFps()
    paused = False
    step_once = False
    overlay_options = OverlayOptions(
        show_confidence=config.show_confidence,
        show_overlay=config.show_overlay,
        show_metrics=True,
    )
    current_confidence = config.confidence
    window_name = f"Drone Detection - {source_name}"
    playback_started_at = time.perf_counter()
    async_worker = AsyncDetectionWorker(detector) if config.async_detection else None

    try:
        while True:
            if paused and not step_once:
                key = cv2.waitKey(30) if not config.no_preview else -1
                action = _handle_key(key, cap, tracker, overlay_options, current_confidence, paused)
                current_confidence = action.confidence
                paused = action.paused if action.paused is not None else paused
                step_once = action.step_once
                if action.quit_requested:
                    break
                continue

            started = time.perf_counter()
            ok, frame = cap.read()
            if not ok:
                break

            frame_number += 1
            run_detection = (frame_number - 1) % config.detection_interval == 0
            detection = None
            if async_worker:
                if run_detection:
                    input_frame = _preprocess_frame(frame) if config.enable_preprocess else frame
                    async_worker.submit(
                        input_frame,
                        confidence=_detector_confidence(config, tracker, current_confidence),
                        frame_number=frame_number,
                    )
                latest_result = async_worker.pop_latest_result()
                if latest_result is not None:
                    detection = select_stable_detection(
                        latest_result.detections,
                        current_marker=tracker.marker,
                        max_jump_pixels=config.max_jump_pixels,
                        min_new_target_confidence=current_confidence,
                    )
                    marker = tracker.update(detection)
                else:
                    marker = tracker.marker
            elif run_detection:
                input_frame = _preprocess_frame(frame) if config.enable_preprocess else frame
                detections = detector.predict(
                    input_frame,
                    confidence=_detector_confidence(config, tracker, current_confidence),
                )
                detection = select_stable_detection(
                    detections,
                    current_marker=tracker.marker,
                    max_jump_pixels=config.max_jump_pixels,
                    min_new_target_confidence=current_confidence,
                )
                marker = tracker.update(detection)
            else:
                marker = tracker.marker
            latency_ms = (time.perf_counter() - started) * 1000
            fps, avg_fps = fps_counter.add_frame_time(max(time.perf_counter() - started, 1e-9))
            timestamp = _timestamp_seconds(cap, frame_number, source_fps)

            metrics = FrameMetrics.from_marker(
                video_name=source_name,
                frame_number=frame_number,
                timestamp=timestamp,
                marker=marker,
                fps=fps,
                avg_fps=avg_fps,
                latency_ms=latency_ms,
            )
            annotated = draw_frame_overlay(frame, marker, metrics, overlay_options)

            if writer:
                writer.write(annotated)
            if logger:
                logger.write(metrics)

            if not config.no_preview:
                cv2.imshow(window_name, annotated)
                wait_ms = _preview_wait_ms(
                    source_fps=source_fps,
                    processing_elapsed=time.perf_counter() - started,
                    realtime=config.realtime,
                    step_once=step_once,
                )
                key = cv2.waitKey(wait_ms)
                action = _handle_key(key, cap, tracker, overlay_options, current_confidence, paused)
                current_confidence = action.confidence
                if action.paused is not None:
                    paused = action.paused
                step_once = action.step_once
                if action.quit_requested:
                    break
                if config.drop_late_frames and config.realtime and not paused and not writer:
                    frame_number = _drop_late_video_frames(
                        cap=cap,
                        source_fps=source_fps,
                        frame_number=frame_number,
                        playback_started_at=playback_started_at,
                        cv2=cv2,
                    )
            else:
                step_once = False

        return ProcessingSummary(
            source=config.source,
            frames_processed=frame_number,
            average_fps=fps_counter.average,
            output_path=str(output_path) if output_path else None,
            csv_log_path=str(csv_path) if csv_path else None,
        )
    finally:
        if async_worker:
            async_worker.close()
        cap.release()
        if writer:
            writer.release()
        if logger:
            logger.close()
        if not config.no_preview:
            cv2.destroyAllWindows()


@dataclass(frozen=True)
class KeyAction:
    quit_requested: bool = False
    paused: bool | None = None
    step_once: bool = False
    confidence: float = 0.35


@dataclass(frozen=True)
class AsyncDetectionResult:
    frame_number: int
    detections: list[Any]


class AsyncDetectionWorker:
    """Runs detector inference off the display thread, keeping only the newest frame."""

    def __init__(self, detector: Detector) -> None:
        self.detector = detector
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._pending: tuple[Any, float, int] | None = None
        self._latest_result: AsyncDetectionResult | None = None
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="drone-detector", daemon=True)
        self._thread.start()

    def submit(self, frame: Any, *, confidence: float, frame_number: int) -> None:
        with self._lock:
            if self._closed:
                return
            self._pending = (frame.copy(), confidence, frame_number)
            self._event.set()

    def pop_latest_result(self) -> AsyncDetectionResult | None:
        with self._lock:
            result = self._latest_result
            self._latest_result = None
            return result

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending = None
            self._event.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        while True:
            self._event.wait()
            with self._lock:
                if self._closed:
                    return
                job = self._pending
                self._pending = None
                self._event.clear()

            if job is None:
                continue

            frame, confidence, frame_number = job
            detections = self.detector.predict(frame, confidence=confidence)
            with self._lock:
                if not self._closed:
                    self._latest_result = AsyncDetectionResult(frame_number, detections)


def _handle_key(
    key: int,
    cap,
    tracker: SmoothedTargetTracker,
    overlay_options: OverlayOptions,
    current_confidence: float,
    paused: bool,
) -> KeyAction:
    if key < 0:
        return KeyAction(confidence=current_confidence)

    char = chr(key & 0xFF).lower()
    if key == 27 or char == "q":
        return KeyAction(quit_requested=True, confidence=current_confidence)
    if char == " ":
        return KeyAction(paused=not paused, confidence=current_confidence)
    if char in {"n", "."}:
        return KeyAction(paused=True, step_once=True, confidence=current_confidence)
    if char == "r":
        cap.set(1, 0)
        tracker.reset()
        return KeyAction(confidence=current_confidence)
    if char == "o":
        overlay_options.show_overlay = not overlay_options.show_overlay
    elif char == "c":
        overlay_options.show_confidence = not overlay_options.show_confidence
    elif char in {"+", "="}:
        current_confidence = min(0.95, current_confidence + 0.05)
        print(f"confidence threshold: {current_confidence:.2f}")
    elif char in {"-", "_"}:
        current_confidence = max(0.01, current_confidence - 0.05)
        print(f"confidence threshold: {current_confidence:.2f}")

    return KeyAction(confidence=current_confidence)


def _detector_confidence(
    config: VideoProcessorConfig,
    tracker: SmoothedTargetTracker,
    current_confidence: float,
) -> float:
    if tracker.marker is None:
        return current_confidence
    return min(current_confidence, config.reacquire_confidence)


def _parse_source(source: str) -> str | int:
    if source.isdigit():
        return int(source)
    return source


def _load_cv2():
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "OpenCV is not installed. Install dependencies with "
            "`python -m pip install -r requirements.txt`."
        ) from exc
    return cv2


def _validate_local_video_source(source: str) -> None:
    if source.isdigit() or "://" in source:
        return

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Video source not found: {source}")
    if path.is_dir():
        raise ValueError(f"Video source is a directory, expected a video file: {source}")
    if path.is_file() and path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise ValueError(
            f"Unsupported video extension '{path.suffix}'. Supported: "
            f"{', '.join(sorted(VIDEO_EXTENSIONS))}"
        )


def _source_name(source: str) -> str:
    if source.isdigit():
        return f"camera_{source}"
    if "://" in source:
        return "stream"
    return Path(source).name


def _resolve_output_path(config: VideoProcessorConfig) -> Path:
    if config.output:
        output = Path(config.output)
        if output.suffix:
            return output
        return output / f"{Path(_source_name(config.source)).stem}_annotated.mp4"
    return Path("outputs") / f"{Path(_source_name(config.source)).stem}_annotated.mp4"


def _timestamp_seconds(cap, frame_number: int, source_fps: float) -> float:
    msec = cap.get(0)
    if msec and msec > 0:
        return msec / 1000
    if source_fps > 0:
        return frame_number / source_fps
    return 0.0


def _preview_wait_ms(
    *,
    source_fps: float,
    processing_elapsed: float,
    realtime: bool,
    step_once: bool,
) -> int:
    if step_once or not realtime or source_fps <= 0:
        return 1
    frame_period = 1.0 / source_fps
    remaining = frame_period - processing_elapsed
    return max(1, round(remaining * 1000))


def _drop_late_video_frames(
    *,
    cap,
    source_fps: float,
    frame_number: int,
    playback_started_at: float,
    cv2,
) -> int:
    if source_fps <= 0:
        return frame_number

    elapsed = time.perf_counter() - playback_started_at
    target_next_frame = int(elapsed * source_fps) + 1
    if target_next_frame <= frame_number + 1:
        return frame_number

    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if frame_count > 0:
        target_next_frame = min(target_next_frame, frame_count)

    next_zero_based = max(0, target_next_frame - 1)
    if not cap.set(cv2.CAP_PROP_POS_FRAMES, next_zero_based):
        return frame_number
    return next_zero_based


def _preprocess_frame(frame):
    """Apply CLAHE + Unsharp Mask enhancement to improve detection recall."""
    if not hasattr(frame, "shape"):
        return frame

    from drone_overlay.preprocess import enhance_frame

    return enhance_frame(frame)
