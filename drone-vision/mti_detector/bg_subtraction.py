"""MOG2 background subtraction with motion compensation for handheld video.

Tuned for drone-against-sky scenarios with camera shake.
Motion compensation: sparse optical flow + affine stabilization before MOG2.
Edge suppression: Canny mask to remove shake artifacts at static boundaries.
"""

from __future__ import annotations

import cv2
import numpy as np


class BackgroundSubtractor:
    """MOG2 background subtractor with configurable morphological cleanup.

    Parameters
    ----------
    history : int
        Number of frames used for background modeling. Default 250.
    var_threshold : int
        Variance threshold. Higher = less sensitive. Default 16.
    learning_rate : float
        -1 for auto, 0.001 fixed recommended for hovering drone. Default -1.
    detect_shadows : bool
        Default False (irrelevant for sky).
    morph_close_kernel : int
        Elliptical kernel size for MORPH_CLOSE. Default 5.
    morph_open_kernel : int
        Elliptical kernel size for MORPH_OPEN. Default 3.
    dilate_kernel : int | None
        Optional dilation kernel. None disables. Default None.
    """

    def __init__(
        self,
        history: int = 250,
        var_threshold: int = 16,
        learning_rate: float = -1.0,
        detect_shadows: bool = False,
        morph_close_kernel: int = 5,
        morph_open_kernel: int = 3,
        dilate_kernel: int | None = None,
    ) -> None:
        self._history = history
        self._var_threshold = var_threshold
        self._learning_rate = learning_rate
        self._detect_shadows = detect_shadows
        self._frame_count = 0

        self._close_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (morph_close_kernel, morph_close_kernel)
        )
        self._open_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (morph_open_kernel, morph_open_kernel)
        )
        self._dilate_kernel = None
        if dilate_kernel is not None:
            self._dilate_kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (dilate_kernel, dilate_kernel)
            )

        self._bg = self._create_mog2()

    def _create_mog2(self) -> cv2.BackgroundSubtractorMOG2:
        return cv2.createBackgroundSubtractorMOG2(
            history=self._history,
            varThreshold=self._var_threshold,
            detectShadows=self._detect_shadows,
        )

    def apply(self, frame: np.ndarray) -> np.ndarray:
        self._frame_count += 1
        fg = self._bg.apply(frame, learningRate=self._learning_rate)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self._close_kernel)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self._open_kernel)
        if self._dilate_kernel is not None:
            fg = cv2.dilate(fg, self._dilate_kernel, iterations=1)
        return fg

    def reset(self) -> None:
        self._bg = self._create_mog2()
        self._frame_count = 0

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def var_threshold(self) -> int:
        return self._var_threshold

    @var_threshold.setter
    def var_threshold(self, value: int) -> None:
        self._var_threshold = value
        self._bg.setVarThreshold(value)


def _compose_affine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Compose two affine matrices: C = B @ A_padded (maps frame0 -> frameN)."""
    a_pad = np.vstack([a.astype(np.float64), [[0, 0, 1]]])
    b_pad = np.vstack([b.astype(np.float64), [[0, 0, 1]]])
    result = (b_pad @ a_pad)[:2, :]
    return result.astype(np.float32)


class MotionEstimator:
    """Estimate inter-frame camera motion via sparse optical flow.

    Tracks Shi-Tomasi corners, fits affine transform with RANSAC.
    Maintains cumulative warp from first frame for temporal consistency.
    """

    def __init__(self, detect_interval: int = 5, max_corners: int = 150,
                 min_corners: int = 8, quality: float = 0.01,
                 min_distance: int = 10, ransac_threshold: float = 3.0) -> None:
        self._detect_interval = detect_interval
        self._max_corners = max_corners
        self._min_corners = min_corners
        self._quality = quality
        self._min_distance = min_distance
        self._ransac_threshold = ransac_threshold

        self._prev_gray: np.ndarray | None = None
        self._prev_corners: np.ndarray | None = None
        self._counter = 0
        self._warp: np.ndarray | None = None
        self._cumulative = np.eye(2, 3, dtype=np.float32)

    def estimate(self, gray: np.ndarray) -> np.ndarray | None:
        """Return per-frame warp (prev->curr) and update cumulative."""
        if self._prev_gray is None:
            self._prev_gray = gray.copy()
            self._detect_corners(gray)
            self._counter = 0
            self._warp = None
            return None

        self._counter += 1

        if self._counter % self._detect_interval == 0 or self._prev_corners is None:
            self._detect_corners(self._prev_gray)

        if self._prev_corners is not None and len(self._prev_corners) >= self._min_corners:
            curr_corners, status, _ = cv2.calcOpticalFlowPyrLK(
                self._prev_gray, gray, self._prev_corners, None,
                winSize=(21, 21), maxLevel=3,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
            )
            if curr_corners is not None:
                mask = status.ravel() == 1
                good_prev = self._prev_corners[mask]
                good_curr = curr_corners[mask]
                if len(good_prev) >= self._min_corners:
                    result = cv2.estimateAffine2D(
                        good_prev, good_curr,
                        method=cv2.RANSAC,
                        ransacReprojThreshold=self._ransac_threshold,
                        maxIters=500,
                        confidence=0.99,
                    )
                    if result is not None:
                        warp = result[0] if isinstance(result, tuple) else result
                        if warp is not None and warp.shape == (2, 3):
                            self._warp = warp
                            self._cumulative = _compose_affine(
                                self._cumulative, warp
                            )

        self._prev_gray = gray.copy()
        return self._warp

    @property
    def cumulative_warp(self) -> np.ndarray:
        return self._cumulative

    def reset(self) -> None:
        self._prev_gray = None
        self._prev_corners = None
        self._counter = 0
        self._warp = None
        self._cumulative = np.eye(2, 3, dtype=np.float32)

    def _detect_corners(self, gray: np.ndarray) -> None:
        corners = cv2.goodFeaturesToTrack(
            gray, maxCorners=self._max_corners, qualityLevel=self._quality,
            minDistance=self._min_distance, blockSize=3,
        )
        if corners is not None:
            self._prev_corners = corners.reshape(-1, 2)
        else:
            self._prev_corners = None

    @staticmethod
    def warp_frame(frame: np.ndarray, warp: np.ndarray | None) -> np.ndarray:
        if warp is None or not isinstance(warp, np.ndarray) or warp.shape != (2, 3):
            return frame
        h, w = frame.shape[:2]
        m = warp.astype(np.float32) if warp.dtype != np.float32 else warp
        return cv2.warpAffine(frame, m, (w, h),
                              flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)


class MotionCompensatedSubtractor:
    """Full MTI pipeline: motion compensation + MOG2 + edge suppression + filtering.

    Designed for handheld smartphone video. Stabilises frames before
    background subtraction, then removes edge artifacts and noise.
    """

    def __init__(
        self,
        history: int = 250,
        var_threshold: int = 20,
        learning_rate: float = -1.0,
        detect_shadows: bool = False,
        morph_close_kernel: int = 5,
        morph_open_kernel: int = 3,
        motion_detect_interval: int = 5,
        min_contour_area: int = 20,
        max_aspect_ratio: float = 5.0,
        min_circularity: float = 0.08,
        temporal_buffer: int = 2,
        edge_dilate: int = 4,
    ) -> None:
        self._bg = BackgroundSubtractor(
            history=history, var_threshold=var_threshold,
            learning_rate=learning_rate, detect_shadows=detect_shadows,
            morph_close_kernel=morph_close_kernel,
            morph_open_kernel=morph_open_kernel,
        )
        self._motion = MotionEstimator(detect_interval=motion_detect_interval)
        self._min_contour_area = min_contour_area
        self._max_aspect_ratio = max_aspect_ratio
        self._min_circularity = min_circularity
        self._edge_dilate = edge_dilate
        self._mask_buffer: list[np.ndarray] = []
        self._temporal_buffer = temporal_buffer

    def apply(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        self._motion.estimate(gray)

        cumulative = self._motion.cumulative_warp

        aligned = MotionEstimator.warp_frame(frame, cumulative)

        fg = self._bg.apply(aligned)

        fg = self._suppress_edges(fg, aligned)

        if self._min_contour_area or self._max_aspect_ratio or self._min_circularity:
            fg = self._filter_contours(fg)

        if self._temporal_buffer > 1:
            fg = self._temporal_and(fg)

        return fg

    def _suppress_edges(self, fg_mask: np.ndarray, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        kernel = np.ones((self._edge_dilate, self._edge_dilate), np.uint8)
        edge_mask = cv2.dilate(edges, kernel, iterations=2)

        fg_without_edges = cv2.bitwise_and(fg_mask, cv2.bitwise_not(edge_mask))

        contours, _ = cv2.findContours(fg_without_edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        restored = np.zeros_like(fg_without_edges)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self._min_contour_area:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            roi_edge = edge_mask[y:y + h, x:x + w]
            roi_orig = fg_mask[y:y + h, x:x + w]
            edge_overlap = (roi_edge & roi_orig).sum()
            total_fg = roi_orig.sum() / 255
            if total_fg > 0 and edge_overlap / total_fg > 0.8:
                continue
            cv2.drawContours(restored, [cnt], -1, 255, -1)

        return restored

    def _filter_contours(self, fg_mask: np.ndarray) -> np.ndarray:
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = np.zeros_like(fg_mask)
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self._min_contour_area:
                continue
            perimeter = cv2.arcLength(cnt, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)
            x, y, w, h = cv2.boundingRect(cnt)
            aspect = max(w, h) / (min(w, h) + 1e-6)
            if aspect > self._max_aspect_ratio:
                continue
            if circularity < self._min_circularity:
                continue
            cv2.drawContours(out, [cnt], -1, 255, -1)
        return out

    def _temporal_and(self, fg_mask: np.ndarray) -> np.ndarray:
        self._mask_buffer.append(fg_mask.copy())
        if len(self._mask_buffer) > self._temporal_buffer:
            self._mask_buffer.pop(0)
        if len(self._mask_buffer) < self._temporal_buffer:
            return fg_mask
        result = self._mask_buffer[0]
        for m in self._mask_buffer[1:]:
            result = cv2.bitwise_and(result, m)
        return result

    def reset(self) -> None:
        self._bg.reset()
        self._motion.reset()
        self._mask_buffer.clear()

    @property
    def frame_count(self) -> int:
        return self._bg.frame_count
