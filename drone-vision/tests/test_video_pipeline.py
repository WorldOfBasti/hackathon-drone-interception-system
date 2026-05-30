import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from drone_overlay.detection import Detection
from drone_overlay.geometry import BoundingBox
from drone_overlay.video import VideoProcessorConfig, process_video


class FakeFrame:
    def copy(self):
        return self


class FakeCapture:
    def __init__(self, frames: list[FakeFrame]) -> None:
        self.frames = frames
        self.index = 0
        self.opened = True

    def isOpened(self) -> bool:
        return self.opened

    def read(self):
        if self.index >= len(self.frames):
            return False, None
        frame = self.frames[self.index]
        self.index += 1
        return True, frame

    def get(self, prop: int) -> float:
        values = {
            FakeCv2.CAP_PROP_POS_MSEC: self.index * (1000 / 30),
            FakeCv2.CAP_PROP_FPS: 30,
            FakeCv2.CAP_PROP_FRAME_WIDTH: 640,
            FakeCv2.CAP_PROP_FRAME_HEIGHT: 480,
        }
        return values.get(prop, 0)

    def set(self, _prop: int, value: int) -> None:
        self.index = value

    def release(self) -> None:
        self.opened = False


class FakeWriter:
    def __init__(self) -> None:
        self.frames_written = 0
        self.opened = True

    def isOpened(self) -> bool:
        return self.opened

    def write(self, _frame) -> None:
        self.frames_written += 1

    def release(self) -> None:
        self.opened = False


class FakeCv2:
    CAP_PROP_POS_MSEC = 0
    CAP_PROP_POS_FRAMES = 1
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5
    FONT_HERSHEY_SIMPLEX = 0
    LINE_AA = 16

    def __init__(self) -> None:
        self.capture = FakeCapture([FakeFrame(), FakeFrame()])
        self.writer = FakeWriter()

    def VideoCapture(self, _source):
        return self.capture

    def VideoWriter_fourcc(self, *_args):
        return 0

    def VideoWriter(self, *_args):
        return self.writer

    def circle(self, *_args, **_kwargs) -> None:
        return None

    def rectangle(self, *_args, **_kwargs) -> None:
        return None

    def putText(self, *_args, **_kwargs) -> None:
        return None

    def line(self, *_args, **_kwargs) -> None:
        return None

    def getTextSize(self, text, *_args):
        return (len(text) * 8, 12), 2

    def destroyAllWindows(self) -> None:
        return None


class FakeDetector:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, _frame, *, confidence: float):
        self.calls += 1
        if self.calls == 1:
            return [Detection(BoundingBox(10, 20, 30, 40), confidence=max(confidence, 0.7))]
        return []


class JumpyDetector:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, _frame, *, confidence: float):
        self.calls += 1
        if self.calls == 1:
            return [Detection(BoundingBox(10, 10, 30, 30), confidence=max(confidence, 0.8))]
        return [
            Detection(BoundingBox(210, 210, 230, 230), confidence=0.95),
            Detection(BoundingBox(12, 12, 32, 32), confidence=0.65),
        ]


class WeakNearbyReacquireDetector:
    def __init__(self) -> None:
        self.calls = 0
        self.confidence_thresholds: list[float] = []

    def predict(self, _frame, *, confidence: float):
        self.calls += 1
        self.confidence_thresholds.append(confidence)
        if self.calls == 1:
            return [Detection(BoundingBox(10, 10, 30, 30), confidence=0.8)]
        return [Detection(BoundingBox(12, 12, 32, 32), confidence=0.24)]


class WeakFarReacquireDetector:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, _frame, *, confidence: float):
        self.calls += 1
        if self.calls == 1:
            return [Detection(BoundingBox(10, 10, 30, 30), confidence=0.8)]
        return [Detection(BoundingBox(210, 210, 230, 230), confidence=0.24)]


class VideoPipelineTests(unittest.TestCase):
    def test_process_video_writes_output_frames_and_csv_rows(self) -> None:
        fake_cv2 = FakeCv2()
        detector = FakeDetector()

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sample.mp4"
            source.touch()
            output = Path(tmpdir) / "annotated.mp4"
            csv_log = Path(tmpdir) / "detections.csv"
            config = VideoProcessorConfig(
                source=str(source),
                model="unused.pt",
                save_output=True,
                output=str(output),
                csv_log=str(csv_log),
                no_preview=True,
                max_missing=2,
            )

            with patch("drone_overlay.video._load_cv2", return_value=fake_cv2):
                with patch.dict(sys.modules, {"cv2": fake_cv2}):
                    summary = process_video(config, detector=detector)

            self.assertEqual(summary.frames_processed, 2)
            self.assertEqual(fake_cv2.writer.frames_written, 2)
            self.assertEqual(detector.calls, 2)
            rows = csv_log.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(rows), 3)
            self.assertIn("video_name,frame_number,timestamp,detected", rows[0])
            self.assertIn("sample.mp4,1,", rows[1])

    def test_process_video_prefers_nearby_detection_over_far_higher_confidence_jump(self) -> None:
        fake_cv2 = FakeCv2()
        detector = JumpyDetector()

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sample.mp4"
            source.touch()
            csv_log = Path(tmpdir) / "detections.csv"
            config = VideoProcessorConfig(
                source=str(source),
                model="unused.pt",
                csv_log=str(csv_log),
                no_preview=True,
                smoothing_alpha=1,
                circle_padding=0,
                min_radius=1,
                max_jump_pixels=50,
            )

            with patch("drone_overlay.video._load_cv2", return_value=fake_cv2):
                with patch.dict(sys.modules, {"cv2": fake_cv2}):
                    process_video(config, detector=detector)

            rows = csv_log.read_text(encoding="utf-8").strip().splitlines()
            self.assertIn(",2,", rows[2])
            self.assertIn(",1,0.6500,22.00,22.00,", rows[2])

    def test_process_video_uses_low_threshold_to_reacquire_nearby_track(self) -> None:
        fake_cv2 = FakeCv2()
        detector = WeakNearbyReacquireDetector()

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sample.mp4"
            source.touch()
            csv_log = Path(tmpdir) / "detections.csv"
            config = VideoProcessorConfig(
                source=str(source),
                model="unused.pt",
                confidence=0.35,
                reacquire_confidence=0.2,
                csv_log=str(csv_log),
                no_preview=True,
                smoothing_alpha=1,
                circle_padding=0,
                min_radius=1,
                max_jump_pixels=50,
            )

            with patch("drone_overlay.video._load_cv2", return_value=fake_cv2):
                with patch.dict(sys.modules, {"cv2": fake_cv2}):
                    process_video(config, detector=detector)

            rows = csv_log.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(detector.confidence_thresholds, [0.35, 0.2])
            self.assertIn(",2,", rows[2])
            self.assertIn(",1,0.2400,22.00,22.00,", rows[2])

    def test_process_video_rejects_weak_far_reacquisition_candidate(self) -> None:
        fake_cv2 = FakeCv2()
        detector = WeakFarReacquireDetector()

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sample.mp4"
            source.touch()
            csv_log = Path(tmpdir) / "detections.csv"
            config = VideoProcessorConfig(
                source=str(source),
                model="unused.pt",
                confidence=0.35,
                reacquire_confidence=0.2,
                csv_log=str(csv_log),
                no_preview=True,
                smoothing_alpha=1,
                circle_padding=0,
                min_radius=1,
                max_jump_pixels=50,
            )

            with patch("drone_overlay.video._load_cv2", return_value=fake_cv2):
                with patch.dict(sys.modules, {"cv2": fake_cv2}):
                    process_video(config, detector=detector)

            rows = csv_log.read_text(encoding="utf-8").strip().splitlines()
            self.assertIn(",2,", rows[2])
            self.assertIn(",0,0.8000,20.00,20.00,", rows[2])


if __name__ == "__main__":
    unittest.main()
