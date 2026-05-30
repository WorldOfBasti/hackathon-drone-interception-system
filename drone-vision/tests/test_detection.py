import unittest

from drone_overlay.detection import (
    Detection,
    OnnxRuntimeYoloDetector,
    non_max_suppression,
    select_best_detection,
    select_stable_detection,
)
from drone_overlay.geometry import BoundingBox, CircleMarker


class DetectionTests(unittest.TestCase):
    def test_select_best_detection_returns_highest_confidence(self) -> None:
        low = Detection(BoundingBox(0, 0, 10, 10), confidence=0.2)
        high = Detection(BoundingBox(10, 10, 20, 20), confidence=0.9)

        self.assertIs(select_best_detection([low, high]), high)

    def test_select_best_detection_handles_empty_iterable(self) -> None:
        self.assertIsNone(select_best_detection([]))

    def test_select_stable_detection_prefers_nearby_target_over_far_higher_confidence(self) -> None:
        current = CircleMarker(center_x=20, center_y=20, radius=10, confidence=0.8, label="drone")
        nearby = Detection(BoundingBox(14, 14, 34, 34), confidence=0.62)
        far_false_positive = Detection(BoundingBox(200, 200, 220, 220), confidence=0.95)

        selected = select_stable_detection(
            [far_false_positive, nearby],
            current_marker=current,
            max_jump_pixels=50,
        )

        self.assertIs(selected, nearby)

    def test_select_stable_detection_allows_weak_nearby_reacquisition(self) -> None:
        current = CircleMarker(center_x=20, center_y=20, radius=10, confidence=0.8, label="drone")
        nearby = Detection(BoundingBox(14, 14, 34, 34), confidence=0.24)

        selected = select_stable_detection(
            [nearby],
            current_marker=current,
            max_jump_pixels=50,
            min_new_target_confidence=0.35,
        )

        self.assertIs(selected, nearby)

    def test_select_stable_detection_rejects_weak_far_reacquisition_candidate(self) -> None:
        current = CircleMarker(center_x=20, center_y=20, radius=10, confidence=0.8, label="drone")
        far_false_positive = Detection(BoundingBox(200, 200, 220, 220), confidence=0.24)

        selected = select_stable_detection(
            [far_false_positive],
            current_marker=current,
            max_jump_pixels=50,
            min_new_target_confidence=0.35,
        )

        self.assertIsNone(selected)

    def test_select_stable_detection_requires_new_targets_to_meet_confidence(self) -> None:
        weak = Detection(BoundingBox(0, 0, 20, 20), confidence=0.24)

        selected = select_stable_detection([weak], min_new_target_confidence=0.35)

        self.assertIsNone(selected)

    def test_select_stable_detection_falls_back_without_nearby_target(self) -> None:
        current = CircleMarker(center_x=20, center_y=20, radius=10, confidence=0.8, label="drone")
        low = Detection(BoundingBox(140, 140, 160, 160), confidence=0.62)
        high = Detection(BoundingBox(200, 200, 220, 220), confidence=0.95)

        selected = select_stable_detection([low, high], current_marker=current, max_jump_pixels=50)

        self.assertIs(selected, high)

    def test_non_max_suppression_removes_duplicate_overlapping_boxes(self) -> None:
        high = Detection(BoundingBox(0, 0, 100, 100), confidence=0.9)
        overlapping = Detection(BoundingBox(5, 5, 105, 105), confidence=0.8)
        distant = Detection(BoundingBox(200, 200, 240, 240), confidence=0.7)

        kept = non_max_suppression([overlapping, distant, high], iou_threshold=0.45)

        self.assertEqual(kept, [high, distant])

    def test_non_max_suppression_keeps_overlapping_boxes_from_different_classes(self) -> None:
        drone = Detection(BoundingBox(0, 0, 100, 100), confidence=0.9, label="drone", class_id=0)
        bird = Detection(BoundingBox(5, 5, 105, 105), confidence=0.8, label="bird", class_id=1)

        kept = non_max_suppression([bird, drone], iou_threshold=0.45)

        self.assertEqual(kept, [drone, bird])

    def test_non_max_suppression_respects_max_detections(self) -> None:
        detections = [
            Detection(
                BoundingBox(index * 20, 0, index * 20 + 10, 10),
                confidence=0.9 - index * 0.1,
            )
            for index in range(3)
        ]

        kept = non_max_suppression(detections, max_detections=2)

        self.assertEqual(kept, detections[:2])

    def test_onnx_detector_score_for_single_class_output(self) -> None:
        class DetectorWithoutInit(OnnxRuntimeYoloDetector):
            pass

        detector = DetectorWithoutInit.__new__(DetectorWithoutInit)

        class FakeRow:
            shape = (5,)

            def __getitem__(self, index):
                return [1, 2, 3, 4, 0.72][index]

        class_id, score = detector._class_and_score(FakeRow())

        self.assertEqual(class_id, 0)
        self.assertEqual(score, 0.72)


if __name__ == "__main__":
    unittest.main()
