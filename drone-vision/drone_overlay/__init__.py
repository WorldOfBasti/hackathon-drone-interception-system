"""Drone detection video overlay MVP."""

from drone_overlay.detection import Detection, select_best_detection
from drone_overlay.geometry import BoundingBox, CircleMarker, circle_from_box
from drone_overlay.tracking import SmoothedTargetTracker

__all__ = [
    "BoundingBox",
    "CircleMarker",
    "Detection",
    "SmoothedTargetTracker",
    "circle_from_box",
    "select_best_detection",
]
