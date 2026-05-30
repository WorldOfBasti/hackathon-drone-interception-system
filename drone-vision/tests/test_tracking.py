import unittest

from drone_overlay.detection import Detection
from drone_overlay.geometry import BoundingBox
from drone_overlay.tracking import SmoothedTargetTracker, TrackerConfig


class TrackingTests(unittest.TestCase):
    def test_tracker_smooths_marker_between_detections(self) -> None:
        tracker = SmoothedTargetTracker(
            TrackerConfig(smoothing_alpha=0.5, circle_padding=0, min_radius=1)
        )

        first = tracker.update(Detection(BoundingBox(0, 0, 20, 20), confidence=0.9))
        second = tracker.update(Detection(BoundingBox(20, 20, 40, 40), confidence=0.8))

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.center_x, 10)
        self.assertEqual(second.center_x, 20)
        self.assertEqual(second.center_y, 20)

    def test_tracker_persists_recently_lost_marker_then_times_out(self) -> None:
        tracker = SmoothedTargetTracker(TrackerConfig(max_missing=2))
        tracker.update(Detection(BoundingBox(0, 0, 20, 20), confidence=0.9))

        first_miss = tracker.update(None)
        second_miss = tracker.update(None)
        third_miss = tracker.update(None)

        self.assertIsNotNone(first_miss)
        self.assertEqual(first_miss.state, "recently_lost")
        self.assertIsNotNone(second_miss)
        self.assertIsNone(third_miss)

    def test_tracker_predicts_missing_marker_motion_with_decay(self) -> None:
        tracker = SmoothedTargetTracker(
            TrackerConfig(
                smoothing_alpha=1,
                circle_padding=0,
                min_radius=1,
                max_missing=3,
                prediction_decay=0.5,
            )
        )
        tracker.update(Detection(BoundingBox(0, 0, 20, 20), confidence=0.9))
        tracker.update(Detection(BoundingBox(10, 0, 30, 20), confidence=0.9))

        first_miss = tracker.update(None)
        second_miss = tracker.update(None)

        self.assertIsNotNone(first_miss)
        self.assertEqual(first_miss.state, "predicted")
        self.assertEqual(first_miss.center_x, 30)
        self.assertIsNotNone(second_miss)
        self.assertEqual(second_miss.state, "predicted")
        self.assertEqual(second_miss.center_x, 35)

    def test_tracker_can_disable_missing_motion_prediction(self) -> None:
        tracker = SmoothedTargetTracker(
            TrackerConfig(
                smoothing_alpha=1,
                circle_padding=0,
                min_radius=1,
                predict_missing_motion=False,
            )
        )
        tracker.update(Detection(BoundingBox(0, 0, 20, 20), confidence=0.9))
        marker = tracker.update(Detection(BoundingBox(10, 0, 30, 20), confidence=0.9))

        missed = tracker.update(None)

        self.assertIsNotNone(marker)
        self.assertIsNotNone(missed)
        self.assertEqual(missed.state, "recently_lost")
        self.assertEqual(missed.center_x, marker.center_x)

    def test_tracker_limits_prediction_frames_before_holding_marker(self) -> None:
        tracker = SmoothedTargetTracker(
            TrackerConfig(
                smoothing_alpha=1,
                circle_padding=0,
                min_radius=1,
                max_prediction_frames=1,
            )
        )
        tracker.update(Detection(BoundingBox(0, 0, 20, 20), confidence=0.9))
        tracker.update(Detection(BoundingBox(10, 0, 30, 20), confidence=0.9))

        first_miss = tracker.update(None)
        second_miss = tracker.update(None)

        self.assertIsNotNone(first_miss)
        self.assertEqual(first_miss.state, "predicted")
        self.assertIsNotNone(second_miss)
        self.assertEqual(second_miss.state, "recently_lost")
        self.assertEqual(second_miss.center_x, first_miss.center_x)

    def test_tracker_handles_no_detection_before_any_target(self) -> None:
        tracker = SmoothedTargetTracker()

        self.assertIsNone(tracker.update(None))

    def test_tracker_requires_confirmed_candidate_before_showing_new_target(self) -> None:
        tracker = SmoothedTargetTracker(TrackerConfig(confirm_frames=2))

        first = tracker.update(Detection(BoundingBox(0, 0, 20, 20), confidence=0.9))
        second = tracker.update(Detection(BoundingBox(2, 2, 22, 22), confidence=0.9))

        self.assertIsNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(second.state, "confirmed")

    def test_tracker_rejects_single_frame_large_jump(self) -> None:
        tracker = SmoothedTargetTracker(TrackerConfig(max_jump_pixels=40, max_missing=2))
        tracker.update(Detection(BoundingBox(0, 0, 20, 20), confidence=0.9))

        marker = tracker.update(Detection(BoundingBox(200, 200, 220, 220), confidence=0.95))

        self.assertIsNotNone(marker)
        self.assertEqual(marker.state, "recently_lost")
        self.assertLess(marker.center_x, 50)


if __name__ == "__main__":
    unittest.main()
