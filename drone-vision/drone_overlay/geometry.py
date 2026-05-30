"""Geometry primitives for marker calculation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoundingBox:
    """Pixel-space detection bounding box."""

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if self.x2 < self.x1 or self.y2 < self.y1:
            raise ValueError(f"Invalid bounding box coordinates: {self}")

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) / 2


@dataclass(frozen=True)
class CircleMarker:
    """Smoothed marker used by the overlay and CSV logger."""

    center_x: float
    center_y: float
    radius: float
    confidence: float
    label: str
    state: str = "confirmed"
    opacity: float = 1.0
    missing_frames: int = 0

    @property
    def detected(self) -> bool:
        return self.state in {"confirmed", "low_confidence"}


def circle_from_box(
    box: BoundingBox,
    *,
    confidence: float,
    label: str,
    padding: float = 12,
    min_radius: float = 12,
    low_confidence_threshold: float | None = None,
) -> CircleMarker:
    """Convert a bounding box to a circle marker with a configurable minimum size."""

    if padding < 0:
        raise ValueError("padding must be non-negative")
    if min_radius <= 0:
        raise ValueError("min_radius must be positive")

    radius = max(box.width, box.height) / 2 + padding
    radius = max(radius, min_radius)
    state = "confirmed"
    if low_confidence_threshold is not None and confidence < low_confidence_threshold:
        state = "low_confidence"

    return CircleMarker(
        center_x=box.center_x,
        center_y=box.center_y,
        radius=radius,
        confidence=confidence,
        label=label,
        state=state,
    )
