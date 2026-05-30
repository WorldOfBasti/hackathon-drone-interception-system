import unittest
from contextlib import redirect_stdout
from io import StringIO

from drone_overlay.overlay import OverlayOptions
from drone_overlay.tracking import SmoothedTargetTracker
from drone_overlay.video import _handle_key, _preview_wait_ms
from drone_overlay.detection import Detection
from drone_overlay.geometry import BoundingBox


class FakeCapture:
    def __init__(self) -> None:
        self.set_calls: list[tuple[int, int]] = []

    def set(self, prop: int, value: int) -> None:
        self.set_calls.append((prop, value))


class VideoControlTests(unittest.TestCase):
    def test_space_toggles_pause_state(self) -> None:
        options = OverlayOptions()
        tracker = SmoothedTargetTracker()
        cap = FakeCapture()

        pause = _handle_key(ord(" "), cap, tracker, options, 0.35, paused=False)
        resume = _handle_key(ord(" "), cap, tracker, options, 0.35, paused=True)

        self.assertTrue(pause.paused)
        self.assertFalse(resume.paused)

    def test_overlay_and_confidence_keys_toggle_options(self) -> None:
        options = OverlayOptions()
        tracker = SmoothedTargetTracker()
        cap = FakeCapture()

        _handle_key(ord("o"), cap, tracker, options, 0.35, paused=False)
        _handle_key(ord("c"), cap, tracker, options, 0.35, paused=False)

        self.assertFalse(options.show_overlay)
        self.assertFalse(options.show_confidence)

    def test_threshold_keys_adjust_confidence(self) -> None:
        options = OverlayOptions()
        tracker = SmoothedTargetTracker()
        cap = FakeCapture()

        with redirect_stdout(StringIO()):
            increased = _handle_key(ord("+"), cap, tracker, options, 0.35, paused=False)
            decreased = _handle_key(ord("-"), cap, tracker, options, 0.35, paused=False)

        self.assertAlmostEqual(increased.confidence, 0.4)
        self.assertAlmostEqual(decreased.confidence, 0.3)

    def test_realtime_preview_waits_for_source_frame_period(self) -> None:
        wait = _preview_wait_ms(
            source_fps=30,
            processing_elapsed=0.010,
            realtime=True,
            step_once=False,
        )

        self.assertEqual(wait, 23)

    def test_preview_does_not_wait_when_realtime_disabled(self) -> None:
        wait = _preview_wait_ms(
            source_fps=30,
            processing_elapsed=0.010,
            realtime=False,
            step_once=False,
        )

        self.assertEqual(wait, 1)

    def test_marker_can_be_held_when_detection_cycle_is_skipped(self) -> None:
        tracker = SmoothedTargetTracker()
        detection = Detection(BoundingBox(0, 0, 20, 20), confidence=0.9)

        confirmed = tracker.update(detection)
        held = tracker.marker

        self.assertEqual(confirmed.state, "confirmed")
        self.assertEqual(held.state, "confirmed")
        self.assertEqual(held.center_x, confirmed.center_x)


if __name__ == "__main__":
    unittest.main()
