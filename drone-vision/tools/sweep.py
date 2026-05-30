#!/usr/bin/env python3
"""5-Iteration Detection-Quality Sweep for drone-vision.

Runs the detection pipeline with progressively more optimizations enabled,
comparing each iteration against the baseline CSV to measure quality impact.

Usage:
  python tools/sweep.py --source <video.mp4> --model <model.onnx> --baseline <baseline.csv>
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.benchmark import CompareResult, compare_csvs, load_csv, print_report

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_CSV = PROJECT_ROOT / "benchmarks" / "baseline" / "20260529-030256" / "baseline.csv"

VIDEO_SOURCE = (
    "provided_data/drive-download-20260528T184848Z-3-001/Air-to-Air/Vibrations.mp4"
)
MODEL_PATH = (
    "provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx"
)


@dataclass
class IterationConfig:
    name: str
    short_name: str
    flags: list[str]


ITERATIONS: list[IterationConfig] = [
    IterationConfig(
        name="1: Image Enhancement",
        short_name="iter_1",
        flags=[
            "--no-wbf",
            "--no-fp-filter",
            "--no-kalman",
            "--vote-window", "1",
            "--vote-threshold", "1",
        ],
    ),
    IterationConfig(
        name="2: +WBF +FP-Filter",
        short_name="iter_2",
        flags=[
            "--no-kalman",
            "--vote-window", "1",
            "--vote-threshold", "1",
        ],
    ),
    IterationConfig(
        name="3: +SAHI",
        short_name="iter_3",
        flags=[
            "--sahi",
            "--no-kalman",
            "--vote-window", "1",
            "--vote-threshold", "1",
        ],
    ),
    IterationConfig(
        name="4: +Temporal (Kalman + Voting)",
        short_name="iter_4",
        flags=[
            "--sahi",
        ],
    ),
    IterationConfig(
        name="5: +TTA Ensemble",
        short_name="iter_5",
        flags=[
            "--sahi",
            "--tta",
        ],
    ),
]


def run_detect(*args: str) -> int:
    cmd = [sys.executable, str(PROJECT_ROOT / "detect_drone.py"), *args]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)
    return result.returncode


def run_benchmark_diff(baseline_csv: str, current_csv: str) -> CompareResult:
    return compare_csvs(baseline_csv, current_csv)


def _get_iter_descriptions(iter_name: str) -> list[str]:
    if "Image Enhancement" in iter_name:
        return [
            "- CLAHE + Unsharp Mask preprocessing enabled",
            "- Model input size: 640x640 (fixed by ONNX model)",
            "- WBF, FP filter, Kalman, SAHI, TTA: all disabled",
        ]
    if "WBF" in iter_name:
        return [
            "- Weighted Boxes Fusion replaces NMS",
            "- False Positive filter (size + aspect ratio) enabled",
            "- Builds on Iteration 1 (preprocessing + 960px)",
        ]
    if "SAHI" in iter_name:
        return [
            "- SAHI tiled inference: 320x320 tiles, 20% overlap",
            "- Tile detections merged via WBF",
            "- Builds on Iteration 2 (WBF + FP filter)",
        ]
    if "Temporal" in iter_name:
        return [
            "- Kalman filter for missed-frame position prediction",
            "- Multi-frame voting: 3 of 5 frames to confirm target",
            "- Builds on Iteration 3 (SAHI)",
        ]
    if "TTA" in iter_name:
        return [
            "- Test-Time Augmentation: 640+960 scales + horizontal flip",
            "- All TTA results merged via WBF",
            "- Builds on Iteration 4 (Temporal Smoothing)",
        ]
    return ["- Unknown iteration"]


def format_summary(iter_cfg: IterationConfig, result: CompareResult) -> str:
    bl = result.baseline_stats
    cr = result.current_stats

    lines = [
        f"## Iteration {iter_cfg.name}",
        "",
        "### Configuration",
        "```",
        *[f"  {f}" for f in iter_cfg.flags],
        "```",
        "",
        "### What Changed",
        *_get_iter_descriptions(iter_cfg.name),
        "",
        "### Results vs Baseline",
        "",
        f"| Metric | Baseline | Iteration | Delta |",
        f"|--------|----------|-----------|-------|",
        f"| Total frames | {bl.total_frames} | {cr.total_frames} | {cr.total_frames - bl.total_frames:+} |",
        f"| Detected frames | {bl.detected_frames} | {cr.detected_frames} | {cr.detected_frames - bl.detected_frames:+} |",
        f"| Detection rate | {bl.detection_rate:.1%} | {cr.detection_rate:.1%} | {cr.detection_rate - bl.detection_rate:+.1%} |",
        f"| Avg confidence | {bl.avg_confidence:.4f} | {cr.avg_confidence:.4f} | {cr.avg_confidence - bl.avg_confidence:+.4f} |",
        f"| Avg FPS | {bl.avg_fps:.2f} | {cr.avg_fps:.2f} | {cr.avg_fps - bl.avg_fps:+.2f} |",
        f"| Avg latency (ms) | {bl.avg_latency:.2f} | {cr.avg_latency:.2f} | {cr.avg_latency - bl.avg_latency:+.2f} |",
        "",
    ]

    if result.lost_detections:
        lines.append(f"- Lost detections: {result.lost_detections}")
    if result.gained_detections:
        lines.append(f"- Gained detections: {result.gained_detections}")

    return "\n".join(lines)


def write_final_summary(
    results: list[tuple[IterationConfig, CompareResult]],
    baseline_csv: str,
    output_dir: Path,
) -> None:
    bl, _ = load_csv(baseline_csv)
    rows = []
    for iter_cfg, result in results:
        cr = result.current_stats
        delta_det = cr.detected_frames - bl.detected_frames
        rows.append(
            f"| {iter_cfg.name:<30} "
            f"| {cr.avg_fps:>8.2f} "
            f"| {cr.avg_latency:>12.2f} "
            f"| {cr.detected_frames:>16} "
            f"| {cr.detection_rate:>13.1%} "
            f"| {cr.avg_confidence:>13.4f} "
            f"| {delta_det:+d} |"
        )

    content = f"""# Detection Quality Sweep — Final Summary

**Baseline**: {baseline_csv}
**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Overview

Five cumulative optimization iterations applied to the drone detection pipeline,
comparing each against the original baseline.

## Results Table

| Iteration | Avg FPS | Avg Latency | Detected Frames | Detection Rate | Avg Confidence | Delta vs Baseline |
|---|---|---|---|---|---|---|
| Baseline | {bl.avg_fps:.2f} | {bl.avg_latency:.2f} | {bl.detected_frames} | {bl.detection_rate:.1%} | {bl.avg_confidence:.4f} | — |
{chr(10).join(rows)}

## Iteration Details

### 1: Image Enhancement
- CLAHE + Unsharp Mask preprocessing
- ONNX model input: 640x640 (auto-detected from model)
- **Goal**: Improve contrast and sharpness for better feature extraction

### 2: Better Box Fusion
- Weighted Boxes Fusion (WBF) replaces NMS
- False Positive filter by size/aspect ratio
- **Goal**: More stable boxes, fewer false positives

### 3: SAHI (Slicing)
- 320x320 tiles with 20% overlap
- Tile detections merged via WBF
- **Goal**: Better recall for small/distant drones

### 4: Temporal Smoothing
- Kalman filter for position prediction during missed frames
- Multi-frame voting (3 of 5) for confirmation
- **Goal**: Fewer lost detections, fewer single-frame false positives

### 5: TTA Ensemble
- Multi-scale (640+960) + horizontal flip
- All TTA results merged via WBF
- **Goal**: Maximum recall through multi-view consensus

## Methodology

- Video: Vibrations.mp4 (393 frames)
- Model: Baseline_yolo11s_Modell.onnx (YOLO11s)
- Runtime: ONNX Runtime CPU (Windows)
- Each iteration compared frame-by-frame against baseline
- Metrics: detection rate, avg confidence, avg FPS, avg latency, frame-level diffs
"""

    output_path = output_dir / "final_summary.md"
    output_path.write_text(content, encoding="utf-8")
    print(f"Final summary written to: {output_path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run 5-iteration detection quality sweep."
    )
    parser.add_argument(
        "--source",
        default=VIDEO_SOURCE,
        help=f"Video file to use. Default: {VIDEO_SOURCE}",
    )
    parser.add_argument(
        "--model",
        default=MODEL_PATH,
        help=f"ONNX model path. Default: {MODEL_PATH}",
    )
    parser.add_argument(
        "--baseline",
        default=str(BASELINE_CSV),
        help=f"Baseline CSV to compare against. Default: {BASELINE_CSV}",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "benchmarks" / "sweep"),
        help="Output directory for sweep results.",
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="Skip running detect_drone, only produce reports from existing CSVs.",
    )
    parser.add_argument(
        "--start-from",
        type=int,
        default=1,
        choices=[1, 2, 3, 4, 5],
        help="Start from this iteration number.",
    )
    args = parser.parse_args(argv)

    baseline_csv = Path(args.baseline)
    if not baseline_csv.exists():
        print(f"error: baseline CSV not found: {baseline_csv}")
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[tuple[IterationConfig, CompareResult]] = []

    for iter_cfg in ITERATIONS:
        iter_num = int(iter_cfg.short_name.split("_")[1])
        if iter_num < args.start_from:
            print(f"Skipping iteration {iter_num} (start-from={args.start_from})")
            continue

        print(f"\n{'='*70}")
        print(f"Iteration {iter_cfg.name}")
        print(f"{'='*70}")

        iter_dir = output_dir / iter_cfg.short_name
        iter_dir.mkdir(parents=True, exist_ok=True)

        csv_output = iter_dir / "detections.csv"

        if not args.no_run:
            cmd = [
                "--source", args.source,
                "--model", args.model,
                "--onnx-provider", "cpu",
                "--no-preview",
                "--csv-log", str(csv_output),
                *iter_cfg.flags,
            ]
            print(f"Running: python detect_drone.py {' '.join(cmd)}")
            rc = run_detect(*cmd)
            if rc != 0:
                print(f"error: detect_drone.py exited with code {rc}")
                print(f"Skipping remainder of iteration {iter_cfg.name}")
                continue

        actual_csv = csv_output
        if not actual_csv.exists():
            csvs = list(iter_dir.glob("*.csv"))
            if not csvs:
                print(f"warning: no CSV files found in {iter_dir}")
                continue
            actual_csv = csvs[0]

        print(f"Comparing against baseline: {baseline_csv}")
        result = run_benchmark_diff(str(baseline_csv), str(actual_csv))
        print_report(result)

        summary = format_summary(iter_cfg, result)
        summary_path = iter_dir / "summary.md"
        summary_path.write_text(summary, encoding="utf-8")
        print(f"Summary written to: {summary_path}")

        report_path = iter_dir / "report.txt"
        report_lines = [
            f"Iteration {iter_cfg.name}",
            f"Baseline: {baseline_csv}",
            f"Current: {actual_csv}",
            "",
            "See summary.md for details.",
        ]
        report_path.write_text("\n".join(report_lines), encoding="utf-8")

        results.append((iter_cfg, result))

    if results:
        write_final_summary(results, str(baseline_csv), output_dir)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
