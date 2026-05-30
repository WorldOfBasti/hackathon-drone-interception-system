import unittest

from drone_overlay.geometry import CircleMarker
from drone_overlay.metrics import FrameMetrics, RollingFps


class MetricsTests(unittest.TestCase):
    def test_frame_metrics_csv_row_matches_required_columns(self) -> None:
        metrics = FrameMetrics.from_marker(
            video_name="fog.mp4",
            frame_number=12,
            timestamp=0.4,
            marker=CircleMarker(50.123, 60.456, 14.5, 0.87654, "drone"),
            fps=24.567,
            avg_fps=22.222,
            latency_ms=41.987,
        )

        row = metrics.to_csv_row()

        self.assertEqual(row["video_name"], "fog.mp4")
        self.assertEqual(row["frame_number"], "12")
        self.assertEqual(row["detected"], "1")
        self.assertEqual(row["confidence"], "0.8765")
        self.assertEqual(row["center_x"], "50.12")
        self.assertEqual(row["latency_ms"], "41.99")

    def test_frame_metrics_no_detection_writes_empty_marker_fields(self) -> None:
        metrics = FrameMetrics.from_marker(
            video_name="empty.mp4",
            frame_number=1,
            timestamp=0.0,
            marker=None,
            fps=10,
            avg_fps=10,
            latency_ms=100,
        )

        row = metrics.to_csv_row()

        self.assertEqual(row["detected"], "0")
        self.assertEqual(row["confidence"], "")
        self.assertEqual(row["center_x"], "")
        self.assertEqual(row["radius"], "")

    def test_rolling_fps_reports_current_and_average(self) -> None:
        counter = RollingFps(window_size=2)

        first, avg_first = counter.add_frame_time(0.1)
        second, avg_second = counter.add_frame_time(0.2)

        self.assertAlmostEqual(first, 10.0)
        self.assertAlmostEqual(avg_first, 10.0)
        self.assertAlmostEqual(second, 5.0)
        self.assertAlmostEqual(avg_second, 7.5)


if __name__ == "__main__":
    unittest.main()
