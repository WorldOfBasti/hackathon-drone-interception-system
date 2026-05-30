"""Runtime metrics and CSV logging."""

from __future__ import annotations

import csv
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from drone_overlay.geometry import CircleMarker


@dataclass(frozen=True)
class FrameMetrics:
    video_name: str
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

    @classmethod
    def from_marker(
        cls,
        *,
        video_name: str,
        frame_number: int,
        timestamp: float,
        marker: CircleMarker | None,
        fps: float,
        avg_fps: float,
        latency_ms: float,
    ) -> "FrameMetrics":
        return cls(
            video_name=video_name,
            frame_number=frame_number,
            timestamp=timestamp,
            detected=bool(marker and marker.detected),
            confidence=marker.confidence if marker else None,
            center_x=marker.center_x if marker else None,
            center_y=marker.center_y if marker else None,
            radius=marker.radius if marker else None,
            fps=fps,
            avg_fps=avg_fps,
            latency_ms=latency_ms,
        )

    def to_csv_row(self) -> dict[str, str]:
        return {
            "video_name": self.video_name,
            "frame_number": str(self.frame_number),
            "timestamp": f"{self.timestamp:.3f}",
            "detected": "1" if self.detected else "0",
            "confidence": self._format_optional(self.confidence, 4),
            "center_x": self._format_optional(self.center_x, 2),
            "center_y": self._format_optional(self.center_y, 2),
            "radius": self._format_optional(self.radius, 2),
            "fps": f"{self.fps:.2f}",
            "avg_fps": f"{self.avg_fps:.2f}",
            "latency_ms": f"{self.latency_ms:.2f}",
        }

    @staticmethod
    def _format_optional(value: float | None, digits: int) -> str:
        if value is None:
            return ""
        return f"{value:.{digits}f}"


class RollingFps:
    """Small rolling FPS helper for current and average preview metrics."""

    def __init__(self, window_size: int = 30) -> None:
        self._values: deque[float] = deque(maxlen=window_size)

    def add_frame_time(self, elapsed_seconds: float) -> tuple[float, float]:
        fps = 0.0 if elapsed_seconds <= 0 else 1.0 / elapsed_seconds
        self._values.append(fps)
        return fps, self.average

    @property
    def average(self) -> float:
        if not self._values:
            return 0.0
        return sum(self._values) / len(self._values)


class CsvDetectionLogger:
    """CSV writer with the PRD-required per-frame columns."""

    fieldnames = [
        "video_name",
        "frame_number",
        "timestamp",
        "detected",
        "confidence",
        "center_x",
        "center_y",
        "radius",
        "fps",
        "avg_fps",
        "latency_ms",
    ]

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self.fieldnames)
        self._writer.writeheader()

    def write(self, metrics: FrameMetrics) -> None:
        self._writer.writerow(metrics.to_csv_row())

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "CsvDetectionLogger":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
