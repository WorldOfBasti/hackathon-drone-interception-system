import unittest

from drone_overlay.video import VideoProcessorConfig, process_video


class VideoValidationTests(unittest.TestCase):
    def test_missing_video_is_reported_before_dependency_loading(self) -> None:
        config = VideoProcessorConfig(
            source="does-not-exist.mp4",
            model="does-not-exist.pt",
            no_preview=True,
        )

        with self.assertRaisesRegex(FileNotFoundError, "Video source not found"):
            process_video(config)

    def test_invalid_confidence_is_rejected(self) -> None:
        config = VideoProcessorConfig(
            source="does-not-exist.mp4",
            model="does-not-exist.pt",
            confidence=1.5,
            no_preview=True,
        )

        with self.assertRaisesRegex(ValueError, "confidence"):
            process_video(config)

    def test_invalid_iou_threshold_is_rejected(self) -> None:
        config = VideoProcessorConfig(
            source="does-not-exist.mp4",
            model="does-not-exist.pt",
            iou_threshold=1.5,
            no_preview=True,
        )

        with self.assertRaisesRegex(ValueError, "iou_threshold"):
            process_video(config)

    def test_invalid_reacquire_confidence_is_rejected(self) -> None:
        config = VideoProcessorConfig(
            source="does-not-exist.mp4",
            model="does-not-exist.pt",
            reacquire_confidence=1.5,
            no_preview=True,
        )

        with self.assertRaisesRegex(ValueError, "reacquire_confidence"):
            process_video(config)

    def test_invalid_max_detections_is_rejected(self) -> None:
        config = VideoProcessorConfig(
            source="does-not-exist.mp4",
            model="does-not-exist.pt",
            max_detections=0,
            no_preview=True,
        )

        with self.assertRaisesRegex(ValueError, "max_detections"):
            process_video(config)

    def test_invalid_prediction_decay_is_rejected(self) -> None:
        config = VideoProcessorConfig(
            source="does-not-exist.mp4",
            model="does-not-exist.pt",
            prediction_decay=1.5,
            no_preview=True,
        )

        with self.assertRaisesRegex(ValueError, "prediction_decay"):
            process_video(config)

    def test_invalid_max_prediction_frames_is_rejected(self) -> None:
        config = VideoProcessorConfig(
            source="does-not-exist.mp4",
            model="does-not-exist.pt",
            max_prediction_frames=-1,
            no_preview=True,
        )

        with self.assertRaisesRegex(ValueError, "max_prediction_frames"):
            process_video(config)


if __name__ == "__main__":
    unittest.main()
