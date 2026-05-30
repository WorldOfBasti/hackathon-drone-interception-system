"""Argument parsing for the drone overlay app."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from drone_overlay.video import VIDEO_EXTENSIONS, VideoProcessorConfig, process_video


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a YOLO drone detector on video and draw a real-time circle overlay.",
    )
    parser.add_argument(
        "--source",
        nargs="+",
        required=True,
        help="Video file(s), camera index, or OpenCV-compatible stream URL.",
    )
    parser.add_argument("--model", required=True, help="Path to a trained YOLO .pt model.")
    parser.add_argument("--confidence", type=float, default=0.35, help="Detection confidence threshold.")
    parser.add_argument("--target-class", default="drone", help="Class label to keep. Default: drone.")
    parser.add_argument(
        "--allow-any-class",
        action="store_true",
        help="Do not filter detections by class label.",
    )
    parser.add_argument("--save-output", action="store_true", help="Save annotated MP4 output.")
    parser.add_argument(
        "--output",
        help="Output file path for one source, or output directory for multiple sources.",
    )
    parser.add_argument("--csv-log", help="CSV log path for one source, or directory for multiple sources.")
    parser.add_argument("--no-preview", action="store_true", help="Disable OpenCV preview window.")
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="Pace preview playback to the source FPS instead of processing as fast as possible.",
    )
    parser.add_argument(
        "--drop-late-frames",
        action="store_true",
        help="For live preview, skip ahead in video files when inference falls behind wall-clock time.",
    )
    parser.add_argument(
        "--async-detection",
        action="store_true",
        help="Run inference in a background worker so preview playback stays smooth.",
    )
    parser.add_argument("--hide-overlay", action="store_true", help="Start with detection overlay hidden.")
    parser.add_argument("--hide-confidence", action="store_true", help="Start with confidence labels hidden.")
    parser.add_argument(
        "--detection-interval",
        type=int,
        default=1,
        help="Run detector every N frames and smooth between detections.",
    )
    parser.add_argument("--smoothing-alpha", type=float, default=0.45, help="EMA smoothing alpha.")
    parser.add_argument("--max-missing", type=int, default=8, help="Frames to keep recently lost marker.")
    parser.add_argument("--circle-padding", type=float, default=12, help="Pixels added around detected box.")
    parser.add_argument("--min-radius", type=float, default=12, help="Minimum circle radius in pixels.")
    parser.add_argument(
        "--confirm-frames",
        type=int,
        default=1,
        help="Require this many consistent detections before showing a new target.",
    )
    parser.add_argument(
        "--max-jump-pixels",
        type=float,
        help="Reject detections that jump farther than this from the current target unless they persist.",
    )
    parser.add_argument(
        "--reacquire-confidence",
        type=float,
        default=0.2,
        help="Lower detector threshold used only to continue an existing nearby track.",
    )
    parser.add_argument(
        "--iou-threshold",
        type=float,
        default=0.45,
        help="NMS IoU threshold for suppressing duplicate boxes.",
    )
    parser.add_argument(
        "--max-detections",
        type=int,
        default=20,
        help="Maximum detector boxes to keep per frame after postprocessing.",
    )
    parser.add_argument(
        "--no-predict-missing-motion",
        dest="predict_missing_motion",
        action="store_false",
        help="Hold recently lost markers in place instead of extrapolating motion.",
    )
    parser.set_defaults(predict_missing_motion=True)
    parser.add_argument(
        "--prediction-decay",
        type=float,
        default=0.85,
        help="Velocity decay applied per missed frame while predicting marker motion.",
    )
    parser.add_argument(
        "--max-prediction-frames",
        type=int,
        default=4,
        help="Stop extrapolating after this many missed frames; marker may still persist.",
    )
    parser.add_argument(
        "--low-confidence",
        type=float,
        default=0.5,
        help="Below this confidence, use low-confidence marker styling.",
    )
    parser.add_argument("--imgsz", type=int, help="Ultralytics inference image size.")
    parser.add_argument("--device", help="Ultralytics/PyTorch device, e.g. cpu, mps, 0.")
    parser.add_argument(
        "--onnx-provider",
        choices=["auto", "coreml", "directml", "cpu", "ultralytics"],
        default="auto",
        help="Runtime for .onnx models. Default: auto, preferring CoreML when available.",
    )
    parser.add_argument(
        "--sahi",
        action="store_true",
        help="Enable SAHI tiled inference for small-object recall.",
    )
    parser.add_argument(
        "--sahi-tile-size",
        type=int,
        default=320,
        help="SAHI tile size in pixels. Default: 320.",
    )
    parser.add_argument(
        "--sahi-overlap",
        type=float,
        default=0.2,
        help="SAHI tile overlap ratio. Default: 0.2.",
    )
    parser.add_argument(
        "--tta",
        action="store_true",
        help="Enable TTA (multi-scale + flip) for maximum recall.",
    )
    parser.add_argument(
        "--tta-scales",
        default="640,960",
        help="Comma-separated TTA scales. Default: 640,960.",
    )
    parser.add_argument(
        "--no-wbf",
        dest="use_wbf",
        action="store_false",
        help="Disable Weighted Boxes Fusion (use NMS instead).",
    )
    parser.set_defaults(use_wbf=True)
    parser.add_argument(
        "--no-fp-filter",
        dest="enable_fp_filter",
        action="store_false",
        help="Disable false-positive size/aspect-ratio filter.",
    )
    parser.set_defaults(enable_fp_filter=True)
    parser.add_argument(
        "--no-preprocess",
        dest="enable_preprocess",
        action="store_false",
        help="Disable CLAHE + Unsharp Mask preprocessing.",
    )
    parser.set_defaults(enable_preprocess=True)
    kalman_group = parser.add_mutually_exclusive_group()
    kalman_group.add_argument(
        "--kalman",
        dest="use_kalman",
        action="store_true",
        help="Enable Kalman filter prediction.",
    )
    kalman_group.add_argument(
        "--no-kalman",
        dest="use_kalman",
        action="store_false",
        help="Disable Kalman filter (default; uses simple velocity prediction).",
    )
    parser.set_defaults(use_kalman=False)
    parser.add_argument(
        "--vote-window",
        type=int,
        default=5,
        help="Multi-frame voting window size. Default: 5.",
    )
    parser.add_argument(
        "--vote-threshold",
        type=int,
        default=1,
        help="Minimum votes to confirm detection. Default: 1.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    sources = _expand_sources(args.source)

    if len(sources) > 1 and args.output and Path(args.output).suffix:
        parser.error("--output must be a directory when processing multiple sources")
    if len(sources) > 1 and args.csv_log and Path(args.csv_log).suffix:
        parser.error("--csv-log must be a directory when processing multiple sources")

    base_config = VideoProcessorConfig(
        source=sources[0],
        model=args.model,
        confidence=args.confidence,
        target_class=args.target_class,
        allow_any_class=args.allow_any_class,
        save_output=args.save_output,
        output=args.output,
        csv_log=args.csv_log,
        no_preview=args.no_preview,
        realtime=args.realtime,
        drop_late_frames=args.drop_late_frames,
        async_detection=args.async_detection,
        show_overlay=not args.hide_overlay,
        show_confidence=not args.hide_confidence,
        detection_interval=args.detection_interval,
        smoothing_alpha=args.smoothing_alpha,
        max_missing=args.max_missing,
        circle_padding=args.circle_padding,
        min_radius=args.min_radius,
        confirm_frames=args.confirm_frames,
        max_jump_pixels=args.max_jump_pixels,
        reacquire_confidence=args.reacquire_confidence,
        iou_threshold=args.iou_threshold,
        max_detections=args.max_detections,
        predict_missing_motion=args.predict_missing_motion,
        prediction_decay=args.prediction_decay,
        max_prediction_frames=args.max_prediction_frames,
        low_confidence=args.low_confidence,
        imgsz=args.imgsz,
        device=args.device,
        onnx_provider=args.onnx_provider,
        use_wbf=args.use_wbf,
        enable_fp_filter=args.enable_fp_filter,
        use_sahi=args.sahi,
        sahi_tile_size=args.sahi_tile_size,
        sahi_overlap=args.sahi_overlap,
        use_tta=args.tta,
        tta_scales=tuple(int(s.strip()) for s in args.tta_scales.split(",") if s.strip()),
        enable_preprocess=args.enable_preprocess,
        use_kalman=args.use_kalman,
        vote_window=args.vote_window,
        vote_threshold=args.vote_threshold,
    )

    try:
        for source in sources:
            config = replace(
                base_config,
                source=source,
                output=_multi_output_path(args.output, source, len(sources)),
                csv_log=_multi_csv_path(args.csv_log, source, len(sources)),
            )
            summary = process_video(config)
            print(
                f"{summary.source}: processed {summary.frames_processed} frames, "
                f"avg FPS {summary.average_fps:.2f}"
            )
            if summary.output_path:
                print(f"annotated output: {summary.output_path}")
            if summary.csv_log_path:
                print(f"csv log: {summary.csv_log_path}")
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}")
        return 1

    return 0


def _multi_output_path(output: str | None, source: str, source_count: int) -> str | None:
    if source_count <= 1:
        return output
    if not output:
        return None
    return str(Path(output) / f"{_source_stem(source)}_annotated.mp4")


def _multi_csv_path(csv_log: str | None, source: str, source_count: int) -> str | None:
    if source_count <= 1:
        return csv_log
    if not csv_log:
        return None
    return str(Path(csv_log) / f"{_source_stem(source)}_detections.csv")


def _source_stem(source: str) -> str:
    if source.isdigit():
        return f"camera_{source}"
    if "://" in source:
        return "stream"
    return Path(source).stem


def _expand_sources(sources: list[str]) -> list[str]:
    expanded: list[str] = []
    for source in sources:
        path = Path(source)
        if source.isdigit() or "://" in source or not path.is_dir():
            expanded.append(source)
            continue

        videos = sorted(
            str(candidate)
            for candidate in path.iterdir()
            if candidate.is_file() and candidate.suffix.lower() in VIDEO_EXTENSIONS
        )
        if not videos:
            raise ValueError(f"No supported video files found in directory: {source}")
        expanded.extend(videos)
    return expanded
