import unittest

from drone_overlay.geometry import BoundingBox, circle_from_box


class GeometryTests(unittest.TestCase):
    def test_circle_from_box_uses_center_and_padded_radius(self) -> None:
        marker = circle_from_box(
            BoundingBox(10, 20, 30, 80),
            confidence=0.82,
            label="drone",
            padding=10,
            min_radius=12,
        )

        self.assertEqual(marker.center_x, 20)
        self.assertEqual(marker.center_y, 50)
        self.assertEqual(marker.radius, 40)
        self.assertEqual(marker.state, "confirmed")

    def test_circle_from_box_enforces_min_radius_for_tiny_drone(self) -> None:
        marker = circle_from_box(
            BoundingBox(100, 100, 104, 104),
            confidence=0.9,
            label="drone",
            padding=2,
            min_radius=12,
        )

        self.assertEqual(marker.radius, 12)

    def test_low_confidence_marker_state(self) -> None:
        marker = circle_from_box(
            BoundingBox(0, 0, 20, 20),
            confidence=0.31,
            label="drone",
            low_confidence_threshold=0.5,
        )

        self.assertEqual(marker.state, "low_confidence")

    def test_invalid_box_raises(self) -> None:
        with self.assertRaises(ValueError):
            BoundingBox(30, 10, 20, 40)


if __name__ == "__main__":
    unittest.main()
