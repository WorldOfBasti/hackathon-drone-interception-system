"""Standalone MOG2 → YOLO drone detection demo.

Own video loop, own CLI, own 3-panel display.
Does NOT use drone_overlay/video.py or drone_overlay/cli.py.

Usage:
    python -m mti_detector.demo_mti \
        --source "provided_data/Air-to-Air 2/Chase_Video.mp4" \
        --model "provided_data/.../Baseline_yolo11s_Modell.onnx" \
        --onnx-provider coreml
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from mti_detector.bg_subtraction import BackgroundSubtractor, MotionCompensatedSubtractor
from mti_detector.mti_guided_detector import MtiGuidedDetector, MtiResult

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="MOG2 → YOLO drone detection demo (standalone MTI pipeline)",
    )
    p.add_argument("--source", required=True, help="Video file path.")
    p.add_argument("--model", required=True, help="Path to YOLO .onnx model.")
    p.add_argument("--confidence", type=float, default=0.35, help="YOLO confidence threshold.")
    p.add_argument("--onnx-provider", default="coreml", choices=["coreml", "cpu", "directml", "auto"])
    p.add_argument("--var-threshold", type=int, default=16, help="MOG2 varThreshold (10-25).")
    p.add_argument("--history", type=int, default=500, help="MOG2 history length.")
    p.add_argument("--learning-rate", type=float, default=0.001, help="MOG2 learning rate (-1=auto).")
    p.add_argument("--warmup-frames", type=int, default=100, help="Frames to warm up MOG2.")
    p.add_argument("--min-area", type=int, default=50, help="Minimum contour area for ROIs.")
    p.add_argument("--max-rois", type=int, default=5, help="Maximum ROIs per frame.")
    p.add_argument("--roi-padding", type=float, default=0.3, help="ROI padding ratio.")
    p.add_argument("--no-preview", action="store_true", help="Headless benchmark, no display.")
    p.add_argument("--save-output", action="store_true", help="Save annotated 3-panel video.")
    p.add_argument("--output", default="mti_output.mp4", help="Output video path.")
    p.add_argument("--realtime", action="store_true", help="Pace playback to video FPS.")
    p.add_argument("--motion-comp", action="store_true", help="Enable motion compensation for handheld video.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    source_path = Path(args.source)
    if not source_path.exists():
        print(f"error: source not found: {args.source}")
        return 1
    if source_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(f"error: unsupported extension: {source_path.suffix}")
        return 1

    model_path = Path(args.model)
    if not model_path.exists():
        print(f"error: model not found: {args.model}")
        return 1

    if args.motion_comp:
        bg = MotionCompensatedSubtractor(
            history=args.history,
            var_threshold=args.var_threshold,
            learning_rate=args.learning_rate,
        )
    else:
        bg = BackgroundSubtractor(
            history=args.history,
            var_threshold=args.var_threshold,
            learning_rate=args.learning_rate,
        )

    detector = MtiGuidedDetector(
        str(model_path),
        onnx_provider=args.onnx_provider,
        confidence=args.confidence,
        bgsubtractor=bg,
        warmup_frames=args.warmup_frames,
        min_contour_area=args.min_area,
        max_rois=args.max_rois,
        roi_padding_ratio=args.roi_padding,
    )

    return run_loop(detector, args)


def run_loop(detector: MtiGuidedDetector, args: argparse.Namespace) -> int:
    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        print(f"error: cannot open video: {args.source}")
        return 1

    source_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)

    writer = None
    if args.save_output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        panel_width = width * 3 + 40
        panel_height = height + 60
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(output_path), fourcc, source_fps, (panel_width, panel_height))
        if not writer.isOpened():
            cap.release()
            print(f"error: cannot write output video: {output_path}")
            return 1

    use_full_frame = False
    show_bg_panel = True
    current_confidence = detector.confidence
    fps_window = deque(maxlen=60)
    playback_started = time.perf_counter()
    frame_number = 1

    mode_counts = {"warmup": 0, "mti": 0, "full_frame_fallback": 0, "full_frame_forced": 0}
    total_yolo_full = 0
    total_yolo_roi = 0

    full_frame_yolo = detector.yolo_detector

    print(f"source: {args.source}  {width}x{height}  {source_fps:.1f} FPS  {total_frames} frames")
    print(f"model:  {args.model}")
    print(f"provider: {args.onnx_provider}  warmup: {args.warmup_frames} frames")
    print(f"controls: [Q]uit [M]ode toggle [B]G toggle [R]eset [+/-] confidence [1/2] varThreshold")
    print("-" * 60)

    while True:
        loop_started = time.perf_counter()

        ok, frame = cap.read()
        if not ok:
            break

        if use_full_frame:
            started = time.perf_counter()
            fg_mask = detector.bg_subtractor.apply(frame)
            detections = full_frame_yolo.predict(frame, confidence=current_confidence)
            elapsed = (time.perf_counter() - started) * 1000
            result = MtiResult(
                fg_mask=fg_mask,
                rois=[],
                detections=detections,
                detection_source="full_frame_forced",
                frame_count=frame_number,
                processing_ms=elapsed,
            )
            mode_counts["full_frame_forced"] += 1
            total_yolo_full += 1
        else:
            started = time.perf_counter()
            result = detector.process_frame(frame, confidence=current_confidence)
            result.processing_ms = (time.perf_counter() - started) * 1000
            mode_counts[result.detection_source] += 1
            if result.detection_source in ("warmup", "full_frame_fallback"):
                total_yolo_full += 1
            elif result.detection_source == "mti":
                total_yolo_roi += len(result.rois) if result.rois else 0

        annotated = draw_3panel(frame, result, height, use_full_frame)

        if writer:
            writer.write(annotated)

        if not args.no_preview:
            cv2.imshow("MTI Drone Detection", annotated)
            wait_ms = _preview_wait_ms(source_fps, time.perf_counter() - loop_started, args.realtime)
            key = cv2.waitKey(wait_ms) & 0xFF

            if key == ord("q") or key == 27:
                break
            elif key == ord("m"):
                use_full_frame = not use_full_frame
                print(f"mode: {'full-frame YOLO' if use_full_frame else 'MOG2 + YOLO'}")
            elif key == ord("b"):
                show_bg_panel = not show_bg_panel
            elif key == ord("r"):
                detector.reset()
                frame_number = 1
                print("MOG2 model reset")
            elif key in (ord("+"), ord("=")):
                current_confidence = min(0.95, current_confidence + 0.05)
                print(f"confidence: {current_confidence:.2f}")
            elif key in (ord("-"), ord("_")):
                current_confidence = max(0.01, current_confidence - 0.05)
                print(f"confidence: {current_confidence:.2f}")
            elif key == ord("1"):
                new_vt = max(8, detector.var_threshold - 1)
                detector.var_threshold = new_vt
                print(f"varThreshold: {new_vt}")
            elif key == ord("2"):
                new_vt = min(30, detector.var_threshold + 1)
                detector.var_threshold = new_vt
                print(f"varThreshold: {new_vt}")
        else:
            if frame_number % 100 == 0:
                print(f"\rframe {frame_number}/{total_frames}  "
                      f"mode: {result.detection_source}  "
                      f"rois: {len(result.rois)}  "
                      f"dets: {len(result.detections)}",
                      end="", flush=True)

        elapsed = time.perf_counter() - loop_started
        fps_window.append(1.0 / max(elapsed, 0.001))
        frame_number += 1

    cap.release()
    if writer:
        writer.release()
    if not args.no_preview:
        cv2.destroyAllWindows()

    avg_fps = sum(fps_window) / max(len(fps_window), 1) if fps_window else 0.0
    total = sum(mode_counts.values())
    print("\n" + "=" * 60)
    print("=== MTI Benchmark ===")
    print(f"Source:       {Path(args.source).name}")
    print(f"Frames:       {total}")
    print(f"Resolution:   {width}x{height}")
    print(f"Avg FPS:      {avg_fps:.1f}")
    print(f"YOLO calls:   full-frame={total_yolo_full}  ROI-based={total_yolo_roi}")
    for mode, count in mode_counts.items():
        if count > 0:
            print(f"  {mode}: {count} frames ({100*count/max(total,1):.1f}%)")
    print("=" * 60)

    return 0


def draw_3panel(frame: np.ndarray, result: MtiResult, panel_height: int, use_full_frame: bool) -> np.ndarray:
    """Build a 3-panel display: Original | MOG2 Mask | YOLO Detections.

    All panels have equal width. A status bar is drawn at the bottom.
    """
    h, w = frame.shape[:2]
    panel_w = w
    status_h = 60

    canvas = np.zeros((h + status_h, panel_w * 3, 3), dtype=np.uint8)

    canvas[0:h, 0:panel_w] = frame

    mask_display = _mask_to_bgr(result.fg_mask) if result.fg_mask is not None else np.zeros_like(frame)
    canvas[0:h, panel_w:panel_w * 2] = mask_display

    det_display = _draw_detections(frame.copy(), result.detections)
    canvas[0:h, panel_w * 2:panel_w * 3] = det_display

    _draw_status_bar(canvas, result, panel_w, h, use_full_frame)

    return canvas


def _mask_to_bgr(mask: np.ndarray) -> np.ndarray:
    if mask is None:
        return np.zeros((1, 1, 3), dtype=np.uint8)
    if mask.ndim == 2:
        bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    else:
        bgr = mask.copy()
    return bgr


def _draw_detections(frame: np.ndarray, detections: list) -> np.ndarray:
    for det in detections:
        x1, y1, x2, y2 = int(det.box.x1), int(det.box.y1), int(det.box.x2), int(det.box.y2)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"{det.label} {det.confidence:.2f}"
        cv2.putText(frame, label, (x1, max(y1 - 6, 0)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)
    return frame


def _draw_status_bar(canvas: np.ndarray, result: MtiResult, panel_w: int, img_h: int, use_full_frame: bool) -> None:
    h = canvas.shape[0]

    mode_text = "MODE: full-frame YOLO" if use_full_frame else f"MODE: {result.detection_source}"
    cv2.putText(canvas, mode_text, (10, h - 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

    info = (f"Frame: {result.frame_count}  "
            f"Processing: {result.processing_ms:.1f}ms  "
            f"ROIs: {len(result.rois)}  "
            f"Dets: {len(result.detections)}  "
            f"Source: {result.detection_source}")
    cv2.putText(canvas, info, (10, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

    hint = "[M]ode  [B]G toggle  [R]eset  [+/-]conf  [1/2]varThr  [Q]uit"
    cv2.putText(canvas, hint, (panel_w * 3 - 520, h - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (150, 150, 150), 1)


def _preview_wait_ms(source_fps: float, processing_elapsed: float, realtime: bool) -> int:
    if not realtime or source_fps <= 0:
        return 1
    frame_period = 1.0 / source_fps
    remaining = frame_period - processing_elapsed
    return max(1, round(remaining * 1000))


if __name__ == "__main__":
    raise SystemExit(main())
