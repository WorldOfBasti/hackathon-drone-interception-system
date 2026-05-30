"""MOG2 → YOLO Moving Target Indication pipeline for drone detection.

Standalone tool — not integrated into drone_overlay pipeline.
Own video loop, own CLI, own display.
"""

from mti_detector.bg_subtraction import BackgroundSubtractor
from mti_detector.mti_guided_detector import MtiGuidedDetector, MtiResult

__all__ = ["BackgroundSubtractor", "MtiGuidedDetector", "MtiResult"]
