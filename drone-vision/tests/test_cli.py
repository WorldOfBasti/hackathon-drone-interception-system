import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from drone_overlay.cli import _expand_sources, build_parser


class CliTests(unittest.TestCase):
    def test_parser_accepts_multiple_sources(self) -> None:
        parser = build_parser()

        args = parser.parse_args(
            [
                "--source",
                "a.mp4",
                "b.mp4",
                "--model",
                "models/drone.pt",
                "--confidence",
                "0.4",
                "--iou-threshold",
                "0.55",
                "--max-detections",
                "5",
                "--reacquire-confidence",
                "0.2",
                "--no-predict-missing-motion",
                "--prediction-decay",
                "0.6",
                "--max-prediction-frames",
                "3",
                "--save-output",
            ]
        )

        self.assertEqual(args.source, ["a.mp4", "b.mp4"])
        self.assertEqual(args.model, "models/drone.pt")
        self.assertEqual(args.confidence, 0.4)
        self.assertEqual(args.iou_threshold, 0.55)
        self.assertEqual(args.max_detections, 5)
        self.assertEqual(args.reacquire_confidence, 0.2)
        self.assertFalse(args.predict_missing_motion)
        self.assertEqual(args.prediction_decay, 0.6)
        self.assertEqual(args.max_prediction_frames, 3)
        self.assertTrue(args.save_output)

    def test_expand_sources_accepts_video_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            folder = Path(tmpdir)
            (folder / "b.mp4").touch()
            (folder / "a.mov").touch()
            (folder / "notes.txt").touch()

            sources = _expand_sources([str(folder)])

        self.assertEqual([Path(source).name for source in sources], ["a.mov", "b.mp4"])

    def test_expand_sources_keeps_camera_and_stream_sources(self) -> None:
        self.assertEqual(_expand_sources(["0", "rtsp://example/stream"]), ["0", "rtsp://example/stream"])


if __name__ == "__main__":
    unittest.main()
