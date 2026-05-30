"""OpenCV drawing helpers for the drone marker and live metrics."""

from __future__ import annotations

import math
from dataclasses import dataclass

from drone_overlay.geometry import CircleMarker
from drone_overlay.metrics import FrameMetrics


@dataclass
class OverlayOptions:
    show_confidence: bool = True
    show_overlay: bool = True
    show_metrics: bool = True


def draw_frame_overlay(frame, marker: CircleMarker | None, metrics: FrameMetrics, options: OverlayOptions):
    """Draw marker and metrics on an OpenCV BGR frame."""

    import cv2

    annotated = frame.copy()
    if options.show_overlay and marker:
        _draw_marker(cv2, annotated, marker, options)
    if options.show_metrics:
        _draw_metrics(cv2, annotated, metrics)
    return annotated


def _draw_marker(cv2, frame, marker: CircleMarker, options: OverlayOptions) -> None:
    center = (round(marker.center_x), round(marker.center_y))
    radius = max(1, round(marker.radius))
    color = _marker_color(marker)
    thickness = 2 if marker.state == "low_confidence" else 3
    halo_thickness = thickness + 4

    if marker.state == "low_confidence":
        _draw_dashed_circle(cv2, frame, center, radius, (0, 0, 0), halo_thickness)
        _draw_dashed_circle(cv2, frame, center, radius, color, thickness)
    else:
        cv2.circle(frame, center, radius, (0, 0, 0), halo_thickness, cv2.LINE_AA)
        cv2.circle(frame, center, radius, color, thickness, cv2.LINE_AA)

    if marker.state in {"recently_lost", "predicted"}:
        cv2.circle(frame, center, max(1, radius - 4), color, 1, cv2.LINE_AA)

    if options.show_confidence:
        label = f"{marker.label} {marker.confidence:.2f}"
        if marker.state == "recently_lost":
            label = f"lost {marker.missing_frames}f"
        elif marker.state == "predicted":
            label = f"pred {marker.missing_frames}f"
        _put_label(cv2, frame, label, (center[0] + radius + 6, center[1] - radius - 6), color)


def _draw_metrics(cv2, frame, metrics: FrameMetrics) -> None:
    lines = [
        f"FPS {metrics.fps:.1f} avg {metrics.avg_fps:.1f}",
        f"Latency {metrics.latency_ms:.1f} ms",
        f"Frame {metrics.frame_number}  Time {metrics.timestamp:.2f}s",
    ]
    if metrics.detected and metrics.confidence is not None:
        lines.append(f"Confidence {metrics.confidence:.2f}")
    else:
        lines.append("Detection none")

    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.55
    thickness = 1
    padding = 8
    line_height = 22
    width = 0
    for line in lines:
        (text_width, _text_height), _baseline = cv2.getTextSize(line, font, scale, thickness)
        width = max(width, text_width)

    panel_width = width + padding * 2
    panel_height = line_height * len(lines) + padding
    cv2.rectangle(frame, (8, 8), (8 + panel_width, 8 + panel_height), (0, 0, 0), -1)
    cv2.rectangle(frame, (8, 8), (8 + panel_width, 8 + panel_height), (255, 255, 255), 1)

    y = 8 + padding + 12
    for line in lines:
        cv2.putText(frame, line, (8 + padding, y), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)
        y += line_height


def _put_label(cv2, frame, text: str, origin: tuple[int, int], color: tuple[int, int, int]) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.55
    thickness = 1
    x = max(8, origin[0])
    y = max(24, origin[1])
    (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
    cv2.rectangle(frame, (x - 4, y - text_height - 6), (x + text_width + 4, y + baseline + 4), (0, 0, 0), -1)
    cv2.putText(frame, text, (x, y), font, scale, color, thickness, cv2.LINE_AA)


def _marker_color(marker: CircleMarker) -> tuple[int, int, int]:
    if marker.state == "recently_lost":
        intensity = max(80, min(255, round(255 * marker.opacity)))
        return (intensity, intensity, intensity)
    if marker.state == "predicted":
        intensity = max(80, min(255, round(255 * marker.opacity)))
        return (intensity, intensity, 255)
    if marker.state == "low_confidence":
        return (0, 210, 255)
    return (60, 255, 60)


def _draw_dashed_circle(
    cv2,
    frame,
    center: tuple[int, int],
    radius: int,
    color: tuple[int, int, int],
    thickness: int,
    dash_degrees: int = 14,
    gap_degrees: int = 10,
) -> None:
    for start in range(0, 360, dash_degrees + gap_degrees):
        end = min(start + dash_degrees, 360)
        points = []
        for degree in range(start, end + 1, 3):
            radians = math.radians(degree)
            x = round(center[0] + math.cos(radians) * radius)
            y = round(center[1] + math.sin(radians) * radius)
            points.append((x, y))
        for first, second in zip(points, points[1:]):
            cv2.line(frame, first, second, color, thickness, cv2.LINE_AA)
