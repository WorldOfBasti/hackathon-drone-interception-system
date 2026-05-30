#!/usr/bin/env python3
"""Benchmark tool for drone-detection-overlay.

Compares detection CSV logs frame-by-frame to detect regressions after code changes.
Calls the existing detect_drone.py internally so it always tests the current code.

Usage:
  Record a baseline (runs detect_drone.py and saves CSVs):
    python tools/benchmark.py record --baseline-dir benchmarks/baseline \\
      -- --source video.mp4 --model model.onnx --no-preview

  Compare current run against recorded baseline:
    python tools/benchmark.py compare --baseline-dir benchmarks/baseline \\
      -- --source video.mp4 --model model.onnx --no-preview

  Compare two specific CSV files directly:
    python tools/benchmark.py diff baseline.csv current.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class FrameRecord:
    frame_number: int
    timestamp: float
    detected: bool
    confidence: float | None
    center_x: float | None
    center_y: float | None
    radius: float | None
    fps: float
    avg_fps: float
    latency_ms: float


@dataclass
class CsvStats:
    path: str
    total_frames: int = 0
    detected_frames: int = 0
    total_confidence: float = 0.0
    total_latency: float = 0.0
    avg_fps_values: list[float] = field(default_factory=list)

    @property
    def detection_rate(self) -> float:
        if self.total_frames == 0:
            return 0.0
        return self.detected_frames / self.total_frames

    @property
    def avg_confidence(self) -> float:
        detected = self.detected_frames
        return self.total_confidence / detected if detected else 0.0

    @property
    def avg_latency(self) -> float:
        if self.total_frames == 0:
            return 0.0
        return self.total_latency / self.total_frames

    @property
    def avg_fps(self) -> float:
        if not self.avg_fps_values:
            return 0.0
        return sum(self.avg_fps_values) / len(self.avg_fps_values)


@dataclass
class FrameDiff:
    frame_number: int
    baseline_detected: bool
    current_detected: bool
    confidence_delta: float | None = None
    position_delta: float | None = None
    latency_delta: float | None = None


@dataclass
class CompareResult:
    baseline_path: str
    current_path: str
    baseline_stats: CsvStats
    current_stats: CsvStats
    diffs: list[FrameDiff]

    @property
    def lost_detections(self) -> int:
        return sum(1 for d in self.diffs if d.baseline_detected and not d.current_detected)

    @property
    def gained_detections(self) -> int:
        return sum(1 for d in self.diffs if not d.baseline_detected and d.current_detected)

    @property
    def confidence_drift(self) -> float:
        deltas = [d.confidence_delta for d in self.diffs if d.confidence_delta is not None]
        if not deltas:
            return 0.0
        return sum(abs(v) for v in deltas) / len(deltas)

    @property
    def fps_change_pct(self) -> float:
        base = self.baseline_stats.avg_fps
        if base == 0:
            return 0.0
        return (self.current_stats.avg_fps - base) / base * 100

    @property
    def latency_change_pct(self) -> float:
        base = self.baseline_stats.avg_latency
        if base == 0:
            return 0.0
        return (self.current_stats.avg_latency - base) / base * 100


def load_csv(path: str | Path) -> tuple[list[FrameRecord], CsvStats]:
    records: list[FrameRecord] = []
    stats = CsvStats(path=str(path))

    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            frame_number = int(row["frame_number"])
            detected = row["detected"] == "1"
            confidence = float(row["confidence"]) if row["confidence"] else None
            center_x = float(row["center_x"]) if row["center_x"] else None
            center_y = float(row["center_y"]) if row["center_y"] else None
            radius = float(row["radius"]) if row["radius"] else None
            fps = float(row["fps"]) if row["fps"] else 0.0
            avg_fps = float(row["avg_fps"]) if row["avg_fps"] else 0.0
            latency_ms = float(row["latency_ms"]) if row["latency_ms"] else 0.0

            records.append(
                FrameRecord(
                    frame_number=frame_number,
                    timestamp=float(row["timestamp"]),
                    detected=detected,
                    confidence=confidence,
                    center_x=center_x,
                    center_y=center_y,
                    radius=radius,
                    fps=fps,
                    avg_fps=avg_fps,
                    latency_ms=latency_ms,
                )
            )

            stats.total_frames += 1
            if detected:
                stats.detected_frames += 1
                if confidence is not None:
                    stats.total_confidence += confidence
            stats.total_latency += latency_ms
            stats.avg_fps_values.append(avg_fps)

    return records, stats


def compare_frames(
    baseline: list[FrameRecord],
    current: list[FrameRecord],
    *,
    position_threshold: float = 10.0,
) -> list[FrameDiff]:
    diffs: list[FrameDiff] = []
    current_map = {r.frame_number: r for r in current}

    for base_frame in baseline:
        cur_frame = current_map.get(base_frame.frame_number)
        if cur_frame is None:
            continue

        if base_frame.detected != cur_frame.detected:
            diffs.append(
                FrameDiff(
                    frame_number=base_frame.frame_number,
                    baseline_detected=base_frame.detected,
                    current_detected=cur_frame.detected,
                    latency_delta=cur_frame.latency_ms - base_frame.latency_ms,
                )
            )
            continue

        if base_frame.detected and cur_frame.detected:
            conf_delta = None
            pos_delta = None
            lat_delta = cur_frame.latency_ms - base_frame.latency_ms

            if base_frame.confidence is not None and cur_frame.confidence is not None:
                conf_delta = cur_frame.confidence - base_frame.confidence
            if (
                base_frame.center_x is not None
                and cur_frame.center_x is not None
                and base_frame.center_y is not None
                and cur_frame.center_y is not None
            ):
                pos_delta = (
                    (cur_frame.center_x - base_frame.center_x) ** 2
                    + (cur_frame.center_y - base_frame.center_y) ** 2
                ) ** 0.5

            if (
                (conf_delta is not None and abs(conf_delta) >= 0.05)
                or (pos_delta is not None and pos_delta >= position_threshold)
                or abs(lat_delta) >= 5.0
            ):
                diffs.append(
                    FrameDiff(
                        frame_number=base_frame.frame_number,
                        baseline_detected=True,
                        current_detected=True,
                        confidence_delta=conf_delta,
                        position_delta=pos_delta,
                        latency_delta=lat_delta,
                    )
                )

    return diffs


def compare_csvs(
    baseline_path: str | Path,
    current_path: str | Path,
) -> CompareResult:
    baseline_records, baseline_stats = load_csv(baseline_path)
    current_records, current_stats = load_csv(current_path)

    diffs = compare_frames(baseline_records, current_records)

    return CompareResult(
        baseline_path=str(baseline_path),
        current_path=str(current_path),
        baseline_stats=baseline_stats,
        current_stats=current_stats,
        diffs=diffs,
    )


def print_report(result: CompareResult) -> None:
    bl = result.baseline_stats
    cr = result.current_stats

    print()
    print(f"Baseline: {result.baseline_path}")
    print(f"Current:  {result.current_path}")
    print()
    print(f"{'Metric':<30} {'Baseline':>12} {'Current':>12} {'Delta':>12}")
    print("-" * 66)
    print(f"{'Total frames':<30} {bl.total_frames:>12} {cr.total_frames:>12} {cr.total_frames - bl.total_frames:>+12}")
    print(f"{'Detected frames':<30} {bl.detected_frames:>12} {cr.detected_frames:>12} {cr.detected_frames - bl.detected_frames:>+12}")
    print(f"{'Detection rate':<30} {bl.detection_rate:>11.1%} {cr.detection_rate:>11.1%} {cr.detection_rate - bl.detection_rate:>+11.1%}")
    print(f"{'Avg confidence':<30} {bl.avg_confidence:>12.4f} {cr.avg_confidence:>12.4f} {cr.avg_confidence - bl.avg_confidence:>+12.4f}")
    print(f"{'Avg FPS':<30} {bl.avg_fps:>12.2f} {cr.avg_fps:>12.2f} {cr.avg_fps - bl.avg_fps:>+12.2f}")
    print(f"{'Avg latency (ms)':<30} {bl.avg_latency:>12.2f} {cr.avg_latency:>12.2f} {cr.avg_latency - bl.avg_latency:>+12.2f}")
    print()

    if not result.diffs:
        print("Result: IDENTICAL — no frame-level differences detected.")
        return

    lost = result.lost_detections
    gained = result.gained_detections
    conf_diffs = [d for d in result.diffs if d.confidence_delta is not None and abs(d.confidence_delta) >= 0.05]
    pos_diffs = [d for d in result.diffs if d.position_delta is not None and d.position_delta >= 10.0]
    lat_diffs = [d for d in result.diffs if d.latency_delta is not None and abs(d.latency_delta) >= 5.0]

    print(f"Frame-level differences: {len(result.diffs)} total")
    if lost:
        print(f"  Lost detections:     {lost:>5}  (was detected in baseline, not in current)")
    if gained:
        print(f"  Gained detections:   {gained:>5}  (new in current, was not in baseline)")
    if conf_diffs:
        print(f"  Confidence shifts:   {len(conf_diffs):>5}  (|delta| >= 0.05)")
    if pos_diffs:
        print(f"  Position shifts:     {len(pos_diffs):>5}  (distance >= 10 px)")
    if lat_diffs:
        print(f"  Latency shifts:      {len(lat_diffs):>5}  (|delta| >= 5 ms)")
    print()

    show = min(len(result.diffs), 20)
    if show > 0:
        print(f"First {show} diffs:")
        print(f"{'Frame':>7} {'Type':<25} {'Detail'}")
        print("-" * 70)
        for diff in result.diffs[:show]:
            if diff.baseline_detected and not diff.current_detected:
                detail = f"LOST"
            elif not diff.baseline_detected and diff.current_detected:
                detail = f"GAINED (new FP?)"
            else:
                parts = []
                if diff.confidence_delta is not None and abs(diff.confidence_delta) >= 0.05:
                    parts.append(f"conf {diff.confidence_delta:+.4f}")
                if diff.position_delta is not None and diff.position_delta >= 10.0:
                    parts.append(f"pos {diff.position_delta:.1f}px")
                if diff.latency_delta is not None and abs(diff.latency_delta) >= 5.0:
                    parts.append(f"lat {diff.latency_delta:+.1f}ms")
                detail = ", ".join(parts) or "drift"
            print(f"{diff.frame_number:>7} {detail}")

    if len(result.diffs) > show:
        print(f"... and {len(result.diffs) - show} more diffs.")


def run_detect(*args: str, cwd: str | Path | None = None) -> int:
    cmd = [sys.executable, "detect_drone.py", *args]
    result = subprocess.run(cmd, cwd=cwd or PROJECT_ROOT)
    return result.returncode


def cmd_record(args: argparse.Namespace) -> int:
    detect_args = list(args.detect_args)
    if detect_args and detect_args[0] == "--":
        detect_args.pop(0)
    run_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    baseline_dir = Path(args.baseline_dir) / run_ts
    baseline_dir.mkdir(parents=True, exist_ok=True)

    detect_args.extend(["--csv-log", str(baseline_dir / "baseline.csv")])

    detect_args.append("--no-preview")

    print(f"Recording baseline to: {baseline_dir}")
    print(f"Running: python detect_drone.py {' '.join(detect_args)}")
    rc = run_detect(*detect_args)

    if rc == 0:
        csv_files = sorted(baseline_dir.glob("*.csv"))
        print(f"Recorded {len(csv_files)} CSV(s):")
        for f in csv_files:
            print(f"  {f}")
    return rc


def cmd_compare(args: argparse.Namespace) -> int:
    detect_args = list(args.detect_args)
    if detect_args and detect_args[0] == "--":
        detect_args.pop(0)
    baseline_dir = Path(args.baseline_dir)

    if not baseline_dir.is_dir():
        print(f"error: baseline directory not found: {baseline_dir}")
        return 1

    baseline_csvs = sorted(baseline_dir.glob("*.csv"))
    if not baseline_csvs:
        print(f"error: no CSV files found in {baseline_dir}")
        return 1

    detect_args.append("--no-preview")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        detect_args.extend(["--csv-log", str(tmp / "current.csv")])

        print(f"Running current code: python detect_drone.py {' '.join(detect_args)}")
        rc = run_detect(*detect_args)

        if rc != 0:
            print(f"error: detect_drone.py exited with code {rc}")
            return rc

        current_csvs = sorted(tmp.glob("*.csv"))
        csv_map = {f.name: f for f in current_csvs}

        all_ok = True
        for baseline_csv in baseline_csvs:
            name = baseline_csv.name
            current_csv = csv_map.get(name)
            if current_csv is None:
                print(f"WARNING: no current CSV matching '{name}' — skipping")
                continue

            result = compare_csvs(baseline_csv, current_csv)
            print_report(result)

            if result.diffs:
                all_ok = False

    return 0 if all_ok else 1


def cmd_diff(args: argparse.Namespace) -> int:
    baseline = Path(args.baseline_csv)
    current = Path(args.current_csv)

    if not baseline.exists():
        print(f"error: baseline CSV not found: {baseline}")
        return 1
    if not current.exists():
        print(f"error: current CSV not found: {current}")
        return 1

    result = compare_csvs(baseline, current)
    print_report(result)
    return 0 if not result.diffs else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark tool — record and compare detection CSV logs.",
    )
    sub = parser.add_subparsers(dest="command")

    rec = sub.add_parser("record", help="Record a baseline by running detect_drone.py")
    rec.add_argument(
        "--baseline-dir",
        required=True,
        help="Directory to store baseline CSV logs.",
    )
    rec.add_argument(
        "detect_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed through to detect_drone.py.",
    )

    cmp = sub.add_parser("compare", help="Compare current run against recorded baseline")
    cmp.add_argument(
        "--baseline-dir",
        required=True,
        help="Directory containing baseline CSV logs.",
    )
    cmp.add_argument(
        "detect_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed through to detect_drone.py.",
    )

    dif = sub.add_parser("diff", help="Compare two CSV files directly")
    dif.add_argument("baseline_csv", help="Path to baseline CSV.")
    dif.add_argument("current_csv", help="Path to current CSV.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "record":
        return cmd_record(args)
    if args.command == "compare":
        return cmd_compare(args)
    if args.command == "diff":
        return cmd_diff(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
