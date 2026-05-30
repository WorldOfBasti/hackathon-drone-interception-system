"""Lightweight marker smoothing and lost-target persistence."""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot

from drone_overlay.detection import Detection
from drone_overlay.geometry import CircleMarker, circle_from_box


@dataclass
class TrackerConfig:
    smoothing_alpha: float = 0.45
    max_missing: int = 8
    circle_padding: float = 12
    min_radius: float = 12
    low_confidence_threshold: float = 0.5
    confirm_frames: int = 1
    max_jump_pixels: float | None = None
    predict_missing_motion: bool = True
    prediction_decay: float = 0.85
    max_prediction_frames: int | None = 4
    use_kalman: bool = False
    vote_window: int = 5
    vote_threshold: int = 1


class SmoothedTargetTracker:
    """Single-target exponential smoother for MVP drone marker stabilization."""

    def __init__(self, config: TrackerConfig | None = None) -> None:
        self.config = config or TrackerConfig()
        if not 0 < self.config.smoothing_alpha <= 1:
            raise ValueError("smoothing_alpha must be in the range (0, 1]")
        if self.config.max_missing < 0:
            raise ValueError("max_missing must be non-negative")
        if self.config.confirm_frames < 1:
            raise ValueError("confirm_frames must be at least 1")
        if self.config.max_jump_pixels is not None and self.config.max_jump_pixels <= 0:
            raise ValueError("max_jump_pixels must be positive when set")
        if not 0 <= self.config.prediction_decay <= 1:
            raise ValueError("prediction_decay must be in the range [0, 1]")
        if (
            self.config.max_prediction_frames is not None
            and self.config.max_prediction_frames < 0
        ):
            raise ValueError("max_prediction_frames must be non-negative when set")
        if self.config.vote_window < 1:
            raise ValueError("vote_window must be at least 1")
        if self.config.vote_threshold < 1 or self.config.vote_threshold > self.config.vote_window:
            raise ValueError("vote_threshold must be between 1 and vote_window")
        self._marker: CircleMarker | None = None
        self._missing_frames = 0
        self._candidate_marker: CircleMarker | None = None
        self._candidate_hits = 0
        self._velocity_x = 0.0
        self._velocity_y = 0.0
        self._velocity_radius = 0.0
        self._kalman_initialized = False
        self._detection_history: list[bool] = [False] * self.config.vote_window
        self._vote_index = 0

    @property
    def marker(self) -> CircleMarker | None:
        return self._marker

    def reset(self) -> None:
        self._marker = None
        self._missing_frames = 0
        self._candidate_marker = None
        self._candidate_hits = 0
        self._velocity_x = 0.0
        self._velocity_y = 0.0
        self._velocity_radius = 0.0
        self._kalman_initialized = False
        self._detection_history = [False] * self.config.vote_window
        self._vote_index = 0

    def update(self, detection: Detection | None) -> CircleMarker | None:
        """Update tracker with a detection or a missed frame."""

        self._record_vote(detection is not None)

        if detection is None:
            return self._handle_missing()

        incoming = circle_from_box(
            detection.box,
            confidence=detection.confidence,
            label=detection.label,
            padding=self.config.circle_padding,
            min_radius=self.config.min_radius,
            low_confidence_threshold=self.config.low_confidence_threshold,
        )

        if self._marker is None:
            if not self._vote_passes():
                return self._confirm_or_hold_candidate(incoming, required_hits=999)
            return self._confirm_or_hold_candidate(incoming)

        if self._is_implausible_jump(incoming):
            previous_marker = self._marker
            confirmed = self._confirm_or_hold_candidate(
                incoming,
                required_hits=max(2, self.config.confirm_frames),
            )
            if confirmed is not None and self._marker is not previous_marker:
                return confirmed
            return self._handle_missing()

        previous_marker = self._marker
        alpha = self.config.smoothing_alpha
        smoothed = CircleMarker(
            center_x=self._lerp(previous_marker.center_x, incoming.center_x, alpha),
            center_y=self._lerp(previous_marker.center_y, incoming.center_y, alpha),
            radius=self._lerp(previous_marker.radius, incoming.radius, alpha),
            confidence=incoming.confidence,
            label=incoming.label,
            state=incoming.state,
            opacity=1.0,
            missing_frames=0,
        )

        if self.config.use_kalman:
            self._kalman_correct(smoothed.center_x, smoothed.center_y)

        self._update_velocity(previous_marker, smoothed)
        self._marker = smoothed
        self._missing_frames = 0
        self._candidate_marker = None
        self._candidate_hits = 0
        return smoothed

    def _confirm_or_hold_candidate(
        self,
        incoming: CircleMarker,
        *,
        required_hits: int | None = None,
    ) -> CircleMarker | None:
        required_hits = required_hits or self.config.confirm_frames
        if required_hits == 1:
            self._marker = incoming
            self._missing_frames = 0
            self._candidate_marker = None
            self._candidate_hits = 0
            self._velocity_x = 0.0
            self._velocity_y = 0.0
            self._velocity_radius = 0.0
            return incoming

        if self._candidate_marker and self._distance(self._candidate_marker, incoming) <= self._candidate_radius():
            self._candidate_hits += 1
            alpha = self.config.smoothing_alpha
            self._candidate_marker = CircleMarker(
                center_x=self._lerp(self._candidate_marker.center_x, incoming.center_x, alpha),
                center_y=self._lerp(self._candidate_marker.center_y, incoming.center_y, alpha),
                radius=self._lerp(self._candidate_marker.radius, incoming.radius, alpha),
                confidence=incoming.confidence,
                label=incoming.label,
                state=incoming.state,
            )
        else:
            self._candidate_marker = incoming
            self._candidate_hits = 1

        if self._candidate_hits >= required_hits:
            self._marker = self._candidate_marker
            self._missing_frames = 0
            self._candidate_marker = None
            self._candidate_hits = 0
            self._velocity_x = 0.0
            self._velocity_y = 0.0
            self._velocity_radius = 0.0
            return self._marker

        return self._marker

    def _is_implausible_jump(self, incoming: CircleMarker) -> bool:
        if self._marker is None or self.config.max_jump_pixels is None:
            return False
        return self._distance(self._marker, incoming) > self.config.max_jump_pixels

    def _candidate_radius(self) -> float:
        base = self.config.max_jump_pixels
        if base is not None:
            return base
        if self._candidate_marker:
            return max(80.0, self._candidate_marker.radius * 4)
        return 80.0

    @staticmethod
    def _distance(first: CircleMarker, second: CircleMarker) -> float:
        return hypot(first.center_x - second.center_x, first.center_y - second.center_y)

    def _handle_missing(self) -> CircleMarker | None:
        if self._marker is None:
            return None

        self._missing_frames += 1
        if self._missing_frames > self.config.max_missing:
            self.reset()
            return None

        opacity = 1.0
        if self.config.max_missing > 0:
            opacity = max(0.2, 1.0 - (self._missing_frames / (self.config.max_missing + 1)))

        center_x = self._marker.center_x
        center_y = self._marker.center_y
        radius = self._marker.radius
        state = "recently_lost"

        should_predict = self._should_predict_missing()

        if (
            should_predict
            and self.config.use_kalman
            and hasattr(self, "_kf")
            and self._kalman_initialized
        ):
            prediction = self._kf.predict()
            center_x = float(prediction[0, 0])
            center_y = float(prediction[1, 0])
            state = "predicted"
        elif should_predict:
            center_x += self._velocity_x
            center_y += self._velocity_y
            radius = max(self.config.min_radius, radius + self._velocity_radius)
            state = "predicted"
            self._decay_velocity()

        self._marker = CircleMarker(
            center_x=center_x,
            center_y=center_y,
            radius=radius,
            confidence=self._marker.confidence,
            label=self._marker.label,
            state=state,
            opacity=opacity,
            missing_frames=self._missing_frames,
        )
        return self._marker

    def _should_predict_missing(self) -> bool:
        if not self.config.predict_missing_motion:
            return False
        if self._velocity_x == 0 and self._velocity_y == 0 and self._velocity_radius == 0:
            return False
        if self.config.max_prediction_frames is None:
            return True
        return self._missing_frames <= self.config.max_prediction_frames

    def _update_velocity(self, previous: CircleMarker, current: CircleMarker) -> None:
        self._velocity_x = current.center_x - previous.center_x
        self._velocity_y = current.center_y - previous.center_y
        self._velocity_radius = current.radius - previous.radius

    def _decay_velocity(self) -> None:
        self._velocity_x *= self.config.prediction_decay
        self._velocity_y *= self.config.prediction_decay
        self._velocity_radius *= self.config.prediction_decay

    def _record_vote(self, detected: bool) -> None:
        self._detection_history[self._vote_index] = detected
        self._vote_index = (self._vote_index + 1) % self.config.vote_window

    def _vote_passes(self) -> bool:
        votes = self._detection_history
        if sum(votes) >= self.config.vote_threshold:
            return True
        return False

    def _kalman_correct(self, x: float, y: float) -> None:
        import numpy as np

        try:
            import cv2
        except ImportError:
            return
        if not hasattr(cv2, "KalmanFilter"):
            return

        if not hasattr(self, "_kf"):
            self._kf = cv2.KalmanFilter(4, 2)
            self._kf.transitionMatrix = np.array([
                [1, 0, 1, 0],
                [0, 1, 0, 1],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ], dtype=np.float32)
            self._kf.measurementMatrix = np.array([
                [1, 0, 0, 0],
                [0, 1, 0, 0],
            ], dtype=np.float32)
            self._kf.processNoiseCov = np.eye(4, dtype=np.float32) * 0.03
            self._kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 0.5
            self._kf.statePre = np.array([[np.float32(x)], [np.float32(y)], [0], [0]], dtype=np.float32)
            self._kf.statePost = self._kf.statePre.copy()
            self._kalman_initialized = True
            return

        measurement = np.array([[np.float32(x)], [np.float32(y)]], dtype=np.float32)
        self._kf.correct(measurement)
        self._kf.predict()
        self._kalman_initialized = True

    @staticmethod
    def _lerp(previous: float, current: float, alpha: float) -> float:
        return previous + (current - previous) * alpha
