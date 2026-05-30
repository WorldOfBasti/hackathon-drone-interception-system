#!/usr/bin/env python3
"""
Small dependency-free drone track viewer for Triangometry exports.

It reads data/*_metadata.json plus rendered drone pixel coordinates from
data/rendered/*_coordinates.json, triangulates rays when at least two
recordings overlap, and displays a top-down X/Z map in Tkinter.

The older ffmpeg dark-blob detector is still available with
--use-video-detection when rendered coordinate JSON is missing.

Important: real metric multi-phone coordinates require a shared AR world or
an external calibration transform for each phone. Without that, the 3D track
written here is a raw debug estimate only.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterable


@dataclass
class Recording:
    base: str
    device: str
    video_path: Path
    metadata_path: Path
    created_epoch: float
    frames: list[dict]
    frame_times: list[float]


@dataclass
class Observation:
    base: str
    device: str
    source: str
    global_t: float
    video_t: float
    frame_index: int
    u: float
    v: float
    score: float


@dataclass
class TrackPoint:
    global_t: float
    rel_t: float
    x: float
    y: float
    z: float
    residual: float
    devices: list[str]


def parse_iso8601_z(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def load_recordings(data_dir: Path) -> list[Recording]:
    recordings: list[Recording] = []
    for metadata_path in sorted(data_dir.glob("*_metadata.json")):
        with metadata_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        session = payload["session"]
        video_name = session.get("videoFilename")
        video_path = data_dir / video_name if video_name else metadata_path.with_name(
            metadata_path.name.replace("_metadata.json", ".mov")
        )
        if not video_path.exists():
            print(f"skip {metadata_path.name}: missing {video_path.name}", file=sys.stderr)
            continue

        frames = payload.get("frames", [])
        if not frames:
            print(f"skip {metadata_path.name}: no frames", file=sys.stderr)
            continue

        base = metadata_path.name.replace("_metadata.json", "")
        recordings.append(
            Recording(
                base=base,
                device=session.get("deviceID", base),
                video_path=video_path,
                metadata_path=metadata_path,
                created_epoch=parse_iso8601_z(session["createdAtISO8601"]),
                frames=frames,
                frame_times=[float(frame["videoPresentationTime"]) for frame in frames],
            )
        )
    return recordings


def nearest_frame(recording: Recording, video_t: float) -> dict:
    idx = bisect.bisect_left(recording.frame_times, video_t)
    if idx <= 0:
        return recording.frames[0]
    if idx >= len(recording.frames):
        return recording.frames[-1]
    prev_frame = recording.frames[idx - 1]
    next_frame = recording.frames[idx]
    if abs(prev_frame["videoPresentationTime"] - video_t) <= abs(
        next_frame["videoPresentationTime"] - video_t
    ):
        return prev_frame
    return next_frame


def read_ppm_token(stream: BinaryIO) -> str | None:
    token = bytearray()
    while True:
        char = stream.read(1)
        if not char:
            return None
        if char == b"#":
            stream.readline()
            continue
        if char.isspace():
            if token:
                return token.decode("ascii")
            continue
        token.extend(char)


def ffmpeg_frames(video_path: Path, sample_fps: float, width: int) -> Iterable[tuple[int, int, bytes]]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        f"fps={sample_fps},scale={width}:-1",
        "-f",
        "image2pipe",
        "-vcodec",
        "ppm",
        "-",
    ]
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert process.stdout is not None
    try:
        while True:
            magic = read_ppm_token(process.stdout)
            if magic is None:
                break
            if magic != "P6":
                raise RuntimeError(f"unexpected ffmpeg frame format: {magic}")
            frame_width = int(read_ppm_token(process.stdout) or "0")
            frame_height = int(read_ppm_token(process.stdout) or "0")
            max_value = int(read_ppm_token(process.stdout) or "0")
            if max_value != 255:
                raise RuntimeError(f"unsupported PPM max value: {max_value}")
            data = process.stdout.read(frame_width * frame_height * 3)
            if len(data) != frame_width * frame_height * 3:
                break
            yield frame_width, frame_height, data
    finally:
        try:
            process.stdout.close()
        except Exception:
            pass
        process.wait()


def is_dark_pixel(r: int, g: int, b: int) -> bool:
    return r < 85 and g < 105 and b < 135 and (r + g + b) < 285


def detect_sky_blob(
    width: int,
    height: int,
    data: bytes,
    last_position: tuple[float, float] | None,
) -> tuple[float, float, float] | None:
    # Candidate pixels: tiny dark blobs in the sky. This is intentionally
    # simple and hackathon-friendly; it is not a general drone detector.
    max_y = int(height * 0.82)
    mask = bytearray(width * height)

    for y in range(2, max_y):
        row = y * width
        pixel_row = row * 3
        for x in range(2, width - 2):
            offset = pixel_row + x * 3
            if is_dark_pixel(data[offset], data[offset + 1], data[offset + 2]):
                mask[row + x] = 1

    seen = bytearray(width * height)
    candidates: list[tuple[float, float, float]] = []

    for y in range(2, max_y):
        for x in range(2, width - 2):
            idx = y * width + x
            if not mask[idx] or seen[idx]:
                continue

            stack = [(x, y)]
            seen[idx] = 1
            area = 0
            sum_x = 0
            sum_y = 0
            min_x = max_x = x
            min_y = max_y_box = y

            while stack:
                cx, cy = stack.pop()
                area += 1
                sum_x += cx
                sum_y += cy
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y_box = max(max_y_box, cy)

                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if nx < 0 or nx >= width or ny < 0 or ny >= height:
                        continue
                    nidx = ny * width + nx
                    if mask[nidx] and not seen[nidx]:
                        seen[nidx] = 1
                        stack.append((nx, ny))

            box_w = max_x - min_x + 1
            box_h = max_y_box - min_y + 1
            aspect = max(box_w / box_h, box_h / box_w)
            if area < 1 or area > 65 or aspect > 4.0:
                continue

            sky_score = surrounding_sky_score(width, height, data, min_x, min_y, max_x, max_y_box)
            if sky_score is None:
                continue

            center_x = sum_x / area
            center_y = sum_y / area
            score = sky_score + 20.0 - abs(area - 5) * 0.8
            if last_position is not None:
                distance = math.hypot(center_x - last_position[0], center_y - last_position[1])
                score += max(0.0, 120.0 - distance) * 1.2

            candidates.append((score, center_x, center_y))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])


def surrounding_sky_score(
    width: int,
    height: int,
    data: bytes,
    min_x: int,
    min_y: int,
    max_x: int,
    max_y: int,
) -> float | None:
    pad = 9
    x0 = max(0, min_x - pad)
    y0 = max(0, min_y - pad)
    x1 = min(width - 1, max_x + pad)
    y1 = min(height - 1, max_y + pad)
    total_r = total_g = total_b = count = 0

    for y in range(y0, y1 + 1, 2):
        for x in range(x0, x1 + 1, 2):
            if min_x <= x <= max_x and min_y <= y <= max_y:
                continue
            offset = (y * width + x) * 3
            total_r += data[offset]
            total_g += data[offset + 1]
            total_b += data[offset + 2]
            count += 1

    if count == 0:
        return None

    avg_r = total_r / count
    avg_g = total_g / count
    avg_b = total_b / count
    brightness = (avg_r + avg_g + avg_b) / 3.0

    if avg_b <= avg_r + 8 or avg_b <= avg_g - 10 or brightness <= 75:
        return None

    return (avg_b - avg_r) + 0.5 * (avg_b - avg_g) + brightness / 20.0


def tap_observations(recordings: list[Recording]) -> list[Observation]:
    observations: list[Observation] = []
    for recording in recordings:
        for frame in recording.frames:
            tap = frame.get("tapPoint")
            if not tap:
                continue
            video_t = float(frame["videoPresentationTime"])
            observations.append(
                Observation(
                    base=recording.base,
                    device=recording.device,
                    source="tap",
                    global_t=recording.created_epoch + video_t,
                    video_t=video_t,
                    frame_index=int(frame["frameIndex"]),
                    u=float(tap["u"]),
                    v=float(tap["v"]),
                    score=999.0,
                )
            )
    return observations


def coordinate_recording_base(path: Path, payload: dict) -> str:
    suffix = "_coordinates.json"
    if path.name.endswith(suffix):
        return path.name[: -len(suffix)]

    source = payload.get("source")
    if isinstance(source, str) and source:
        return Path(source).stem

    return path.stem


def detection_center(frame: dict) -> tuple[dict, dict] | None:
    marker = frame.get("tracked_marker")
    if isinstance(marker, dict) and isinstance(marker.get("center"), dict):
        return marker, marker["center"]

    selected = frame.get("selected_detection")
    if isinstance(selected, dict) and isinstance(selected.get("center"), dict):
        return selected, selected["center"]

    return None


def load_rendered_observations(
    recordings: list[Recording],
    rendered_dir: Path,
    include_taps: bool,
) -> list[Observation]:
    observations = tap_observations(recordings) if include_taps else []
    by_base = {recording.base: recording for recording in recordings}
    coordinate_paths = sorted(rendered_dir.glob("*_coordinates.json"))

    if not coordinate_paths:
        print(f"no rendered coordinate JSON found in {rendered_dir}", file=sys.stderr)
        return observations

    for coordinate_path in coordinate_paths:
        with coordinate_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        base = coordinate_recording_base(coordinate_path, payload)
        recording = by_base.get(base)
        if recording is None:
            print(f"skip {coordinate_path.name}: no matching metadata for {base}", file=sys.stderr)
            continue

        video = payload.get("video", {})
        source_width = float(video.get("width") or 0)
        source_height = float(video.get("height") or 0)

        for rendered_frame in payload.get("frames", []):
            center_result = detection_center(rendered_frame)
            if center_result is None:
                continue

            marker, center = center_result
            video_t = float(rendered_frame.get("timestamp_seconds", 0.0))
            metadata_frame = nearest_frame(recording, video_t)
            resolution = metadata_frame["imageResolution"]
            target_width = float(resolution["width"])
            target_height = float(resolution["height"])

            if source_width > 0:
                u = float(center["x"]) * target_width / source_width
            else:
                u = float(center["x"])
            if source_height > 0:
                v = float(center["y"]) * target_height / source_height
            else:
                v = float(center["y"])

            score = float(marker.get("confidence") or 0.0)
            observations.append(
                Observation(
                    base=recording.base,
                    device=recording.device,
                    source="rendered",
                    global_t=recording.created_epoch + video_t,
                    video_t=video_t,
                    frame_index=int(metadata_frame["frameIndex"]),
                    u=u,
                    v=v,
                    score=score,
                )
            )

    observations.sort(key=lambda obs: (obs.global_t, obs.device))
    return observations


def cache_is_fresh(cache_path: Path, recordings: list[Recording]) -> bool:
    if not cache_path.exists():
        return False
    cache_mtime = cache_path.stat().st_mtime
    for recording in recordings:
        if recording.video_path.stat().st_mtime > cache_mtime:
            return False
        if recording.metadata_path.stat().st_mtime > cache_mtime:
            return False
    return True


def load_observation_cache(cache_path: Path) -> list[Observation]:
    observations: list[Observation] = []
    with cache_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            observations.append(
                Observation(
                    base=row["base"],
                    device=row["device"],
                    source=row["source"],
                    global_t=float(row["global_t"]),
                    video_t=float(row["video_t"]),
                    frame_index=int(row["frame_index"]),
                    u=float(row["u"]),
                    v=float(row["v"]),
                    score=float(row["score"]),
                )
            )
    return observations


def write_observations(cache_path: Path, observations: list[Observation]) -> None:
    with cache_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["base", "device", "source", "global_t", "video_t", "frame_index", "u", "v", "score"],
        )
        writer.writeheader()
        for obs in observations:
            writer.writerow(
                {
                    "base": obs.base,
                    "device": obs.device,
                    "source": obs.source,
                    "global_t": f"{obs.global_t:.6f}",
                    "video_t": f"{obs.video_t:.6f}",
                    "frame_index": obs.frame_index,
                    "u": f"{obs.u:.3f}",
                    "v": f"{obs.v:.3f}",
                    "score": f"{obs.score:.3f}",
                }
            )


def detect_observations(
    recordings: list[Recording],
    data_dir: Path,
    sample_fps: float,
    width: int,
    force: bool,
) -> list[Observation]:
    cache_path = data_dir / "drone_observations_auto.csv"
    if not force and cache_is_fresh(cache_path, recordings):
        return load_observation_cache(cache_path)

    observations = tap_observations(recordings)

    for recording in recordings:
        print(f"detect {recording.video_path.name} ...", file=sys.stderr)
        last_position: tuple[float, float] | None = None
        misses = 0
        frame_number = 0
        for scaled_w, scaled_h, data in ffmpeg_frames(recording.video_path, sample_fps, width):
            video_t = frame_number / sample_fps
            frame_number += 1
            if video_t > recording.frame_times[-1] + 0.25:
                break

            detection = detect_sky_blob(scaled_w, scaled_h, data, last_position)
            if detection is None:
                misses += 1
                if misses >= 4:
                    last_position = None
                continue

            score, x, y = detection
            misses = 0
            last_position = (x, y)
            metadata_frame = nearest_frame(recording, video_t)
            resolution = metadata_frame["imageResolution"]
            u = x * float(resolution["width"]) / scaled_w
            v = y * float(resolution["height"]) / scaled_h

            observations.append(
                Observation(
                    base=recording.base,
                    device=recording.device,
                    source="auto",
                    global_t=recording.created_epoch + video_t,
                    video_t=video_t,
                    frame_index=int(metadata_frame["frameIndex"]),
                    u=u,
                    v=v,
                    score=score,
                )
            )

    observations.sort(key=lambda obs: (obs.global_t, obs.device))
    write_observations(cache_path, observations)
    return observations


def normalize(vec: list[float]) -> list[float]:
    length = math.sqrt(sum(value * value for value in vec))
    if length == 0:
        return [0.0, 0.0, 0.0]
    return [value / length for value in vec]


def mat_vec(matrix: list[list[float]], vec: list[float]) -> list[float]:
    return [
        matrix[0][0] * vec[0] + matrix[0][1] * vec[1] + matrix[0][2] * vec[2],
        matrix[1][0] * vec[0] + matrix[1][1] * vec[1] + matrix[1][2] * vec[2],
        matrix[2][0] * vec[0] + matrix[2][1] * vec[1] + matrix[2][2] * vec[2],
    ]


def ray_from_observation(recording: Recording, obs: Observation) -> tuple[list[float], list[float]]:
    frame = nearest_frame(recording, obs.video_t)
    transform = frame["cameraTransform"]
    intrinsics = frame["cameraIntrinsics"]
    fx = float(intrinsics[0][0])
    fy = float(intrinsics[1][1])
    cx = float(intrinsics[0][2])
    cy = float(intrinsics[1][2])

    # ARKit camera looks along local -Z. Image coordinates have +Y downward.
    camera_dir = normalize([(obs.u - cx) / fx, -(obs.v - cy) / fy, -1.0])
    rotation = [row[:3] for row in transform[:3]]
    world_dir = normalize(mat_vec(rotation, camera_dir))
    origin = [float(transform[0][3]), float(transform[1][3]), float(transform[2][3])]
    return origin, world_dir


def solve_3x3(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    augmented = [matrix[i][:] + [vector[i]] for i in range(3)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-9:
            return None
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        pivot_value = augmented[col][col]
        for item in range(col, 4):
            augmented[col][item] /= pivot_value
        for row in range(3):
            if row == col:
                continue
            factor = augmented[row][col]
            for item in range(col, 4):
                augmented[row][item] -= factor * augmented[col][item]
    return [augmented[row][3] for row in range(3)]


def triangulate_rays(rays: list[tuple[list[float], list[float]]]) -> tuple[list[float], float] | None:
    if len(rays) < 2:
        return None

    a = [[0.0, 0.0, 0.0] for _ in range(3)]
    b = [0.0, 0.0, 0.0]
    for origin, direction in rays:
        dx, dy, dz = normalize(direction)
        projection = [
            [1.0 - dx * dx, -dx * dy, -dx * dz],
            [-dy * dx, 1.0 - dy * dy, -dy * dz],
            [-dz * dx, -dz * dy, 1.0 - dz * dz],
        ]
        for row in range(3):
            for col in range(3):
                a[row][col] += projection[row][col]
            b[row] += (
                projection[row][0] * origin[0]
                + projection[row][1] * origin[1]
                + projection[row][2] * origin[2]
            )

    point = solve_3x3(a, b)
    if point is None:
        return None

    distances = []
    for origin, direction in rays:
        ox, oy, oz = origin
        dx, dy, dz = normalize(direction)
        px, py, pz = point
        rel = [px - ox, py - oy, pz - oz]
        t = rel[0] * dx + rel[1] * dy + rel[2] * dz
        closest = [ox + t * dx, oy + t * dy, oz + t * dz]
        distances.append(math.sqrt(sum((point[i] - closest[i]) ** 2 for i in range(3))))

    return point, sum(distances) / len(distances)


def track_distance(a: TrackPoint, b: TrackPoint) -> float:
    return math.sqrt((b.x - a.x) ** 2 + (b.y - a.y) ** 2 + (b.z - a.z) ** 2)


def build_track(
    recordings: list[Recording],
    observations: list[Observation],
    bin_seconds: float,
) -> list[TrackPoint]:
    by_base = {recording.base: recording for recording in recordings}
    start_epoch = min(recording.created_epoch for recording in recordings)
    bins: dict[float, list[Observation]] = {}
    for obs in observations:
        if obs.source not in {"rendered", "auto", "tap"}:
            continue
        key = round(obs.global_t / bin_seconds) * bin_seconds
        bins.setdefault(key, []).append(obs)

    track: list[TrackPoint] = []
    for global_t in sorted(bins):
        best_by_base: dict[str, Observation] = {}
        for obs in bins[global_t]:
            prev = best_by_base.get(obs.base)
            if prev is None or obs.score > prev.score:
                best_by_base[obs.base] = obs

        if len(best_by_base) < 2:
            continue

        rays = []
        devices = []
        for obs in best_by_base.values():
            recording = by_base.get(obs.base)
            if recording is None:
                continue
            rays.append(ray_from_observation(recording, obs))
            devices.append(obs.device)

        result = triangulate_rays(rays)
        if result is None:
            continue

        point, residual = result
        track.append(
            TrackPoint(
                global_t=global_t,
                rel_t=global_t - start_epoch,
                x=point[0],
                y=point[1],
                z=point[2],
                residual=residual,
                devices=devices,
            )
        )

    return track


def smooth_track(
    track: list[TrackPoint],
    step_seconds: float,
    max_speed: float,
    alpha: float,
    measurement_gap_seconds: float,
    median_window_seconds: float,
    residual_gate: float,
    max_acceleration: float,
    velocity_decay: float = 0.86,
) -> list[TrackPoint]:
    if not track:
        return []

    alpha = min(max(alpha, 0.01), 1.0)
    step_seconds = max(step_seconds, 0.001)
    max_speed = max(max_speed, 0.001)
    measurement_gap_seconds = max(measurement_gap_seconds, step_seconds)
    median_window_seconds = max(median_window_seconds, step_seconds)
    max_acceleration = max(max_acceleration, 0.001)

    ordered = sorted(track, key=lambda point: point.rel_t)
    robust_measurements = robust_track_measurements(
        ordered,
        step_seconds=step_seconds,
        median_window_seconds=median_window_seconds,
        residual_gate=residual_gate,
    )
    measurement_times = [point.rel_t for point in robust_measurements]
    raw_rel_times = [point.rel_t for point in ordered]
    start_rel = raw_rel_times[0]
    end_rel = raw_rel_times[-1]
    start_global_offset = ordered[0].global_t - ordered[0].rel_t

    smoothed: list[TrackPoint] = []
    position: list[float] | None = None
    velocity = [0.0, 0.0, 0.0]
    last_rel: float | None = None

    steps = int(math.floor((end_rel - start_rel) / step_seconds)) + 1
    for index in range(steps + 1):
        rel_t = round(start_rel + index * step_seconds, 6)
        if rel_t > end_rel + 1e-9:
            break

        nearest = nearest_track_point(robust_measurements, measurement_times, rel_t)
        measurement = nearest if nearest and abs(nearest.rel_t - rel_t) <= measurement_gap_seconds else None
        dt = step_seconds if last_rel is None else max(rel_t - last_rel, 1e-6)

        if position is None:
            if measurement is None:
                continue
            position = [measurement.x, measurement.y, measurement.z]
        elif measurement is not None:
            error = [measurement.x - position[0], measurement.y - position[1], measurement.z - position[2]]
            distance = math.sqrt(sum(value * value for value in error))
            if distance > 1e-9:
                desired_velocity = clamp_vector([value * alpha / dt for value in error], max_speed)
                velocity_delta = clamp_vector(
                    [desired_velocity[i] - velocity[i] for i in range(3)],
                    max_acceleration * dt,
                )
                velocity = [velocity[i] + velocity_delta[i] for i in range(3)]
                position = [position[i] + velocity[i] * dt for i in range(3)]
        else:
            position = [position[i] + velocity[i] * dt for i in range(3)]
            velocity = [value * velocity_decay for value in velocity]

        source = measurement or nearest or nearest_track_point(ordered, raw_rel_times, rel_t) or ordered[-1]
        smoothed.append(
            TrackPoint(
                global_t=start_global_offset + rel_t,
                rel_t=rel_t,
                x=position[0],
                y=position[1],
                z=position[2],
                residual=source.residual,
                devices=source.devices,
            )
        )
        last_rel = rel_t

    return smoothed


def robust_track_measurements(
    track: list[TrackPoint],
    step_seconds: float,
    median_window_seconds: float,
    residual_gate: float,
) -> list[TrackPoint]:
    if not track:
        return []

    start_rel = track[0].rel_t
    end_rel = track[-1].rel_t
    start_global_offset = track[0].global_t - track[0].rel_t
    left = 0
    right = 0
    measurements: list[TrackPoint] = []

    steps = int(math.floor((end_rel - start_rel) / step_seconds)) + 1
    for index in range(steps + 1):
        rel_t = round(start_rel + index * step_seconds, 6)
        if rel_t > end_rel + 1e-9:
            break

        half_window = median_window_seconds / 2.0
        while left < len(track) and track[left].rel_t < rel_t - half_window:
            left += 1
        while right < len(track) and track[right].rel_t <= rel_t + half_window:
            right += 1

        window = [point for point in track[left:right] if point.residual <= residual_gate]
        if len(window) < 3:
            window = track[left:right]
        if not window:
            continue

        nearest = min(window, key=lambda point: abs(point.rel_t - rel_t))
        measurements.append(
            TrackPoint(
                global_t=start_global_offset + rel_t,
                rel_t=rel_t,
                x=median([point.x for point in window]),
                y=median([point.y for point in window]),
                z=median([point.z for point in window]),
                residual=median([point.residual for point in window]),
                devices=nearest.devices,
            )
        )

    return measurements


def vector_length(vec: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vec))


def clamp_vector(vec: list[float], max_length: float) -> list[float]:
    length = vector_length(vec)
    if length <= max_length or length < 1e-9:
        return vec[:]
    return [value * max_length / length for value in vec]


def nearest_track_point(
    track: list[TrackPoint],
    rel_times: list[float],
    rel_t: float,
) -> TrackPoint | None:
    if not track:
        return None

    idx = bisect.bisect_left(rel_times, rel_t)
    candidates = []
    if idx < len(track):
        candidates.append(track[idx])
    if idx > 0:
        candidates.append(track[idx - 1])
    if not candidates:
        return None
    return min(candidates, key=lambda point: abs(point.rel_t - rel_t))


def write_track_csv(path: Path, track: list[TrackPoint]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["global_t", "relative_t", "x", "y", "z", "residual", "devices"],
        )
        writer.writeheader()
        for point in track:
            writer.writerow(
                {
                    "global_t": f"{point.global_t:.6f}",
                    "relative_t": f"{point.rel_t:.3f}",
                    "x": f"{point.x:.6f}",
                    "y": f"{point.y:.6f}",
                    "z": f"{point.z:.6f}",
                    "residual": f"{point.residual:.6f}",
                    "devices": "+".join(point.devices),
                }
            )


def write_summary_json(
    path: Path,
    recordings: list[Recording],
    observations: list[Observation],
    raw_track: list[TrackPoint],
    smoothed_track: list[TrackPoint],
    observation_mode: str,
    bin_seconds: float,
    rendered_dir: Path | None,
    smoothing_enabled: bool,
    smooth_step_seconds: float,
    smooth_max_speed: float,
    smooth_alpha: float,
    smooth_measurement_gap_seconds: float,
    smooth_median_window_seconds: float,
    smooth_residual_gate: float,
    smooth_max_acceleration: float,
) -> None:
    summary = {
        "warning": (
            "Raw debug triangulation only unless all ARKit camera transforms are already "
            "in the same shared world coordinate system."
        ),
        "observationMode": observation_mode,
        "binSeconds": bin_seconds,
        "renderedDirectory": str(rendered_dir) if rendered_dir else None,
        "smoothing": {
            "enabled": smoothing_enabled,
            "stepSeconds": smooth_step_seconds,
            "maxSpeedMetersPerSecond": smooth_max_speed,
            "maxAccelerationMetersPerSecondSquared": smooth_max_acceleration,
            "alpha": smooth_alpha,
            "measurementGapSeconds": smooth_measurement_gap_seconds,
            "medianWindowSeconds": smooth_median_window_seconds,
            "residualGateMeters": smooth_residual_gate,
        },
        "recordings": [
            {
                "base": recording.base,
                "device": recording.device,
                "frames": len(recording.frames),
                "duration": recording.frame_times[-1],
                "createdAtEpoch": recording.created_epoch,
            }
            for recording in recordings
        ],
        "observations": len(observations),
        "renderedObservations": sum(1 for obs in observations if obs.source == "rendered"),
        "autoObservations": sum(1 for obs in observations if obs.source == "auto"),
        "tapObservations": sum(1 for obs in observations if obs.source == "tap"),
        "rawTrackPoints": len(raw_track),
        "smoothedTrackPoints": len(smoothed_track),
        "medianRawResidualMeters": median([point.residual for point in raw_track]) if raw_track else None,
        "medianSmoothedResidualMeters": median([point.residual for point in smoothed_track]) if smoothed_track else None,
        "maxRawStepSpeedMetersPerSecond": max_step_speed(raw_track),
        "maxSmoothedStepSpeedMetersPerSecond": max_step_speed(smoothed_track),
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")


def median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def max_step_speed(track: list[TrackPoint]) -> float | None:
    speeds = []
    for previous, current in zip(track, track[1:]):
        dt = current.rel_t - previous.rel_t
        if dt > 0:
            speeds.append(track_distance(previous, current) / dt)
    return max(speeds) if speeds else None


def recording_position_at(recording: Recording, rel_epoch: float, start_epoch: float) -> tuple[float, float, float]:
    video_t = max(0.0, min(recording.frame_times[-1], start_epoch + rel_epoch - recording.created_epoch))
    frame = nearest_frame(recording, video_t)
    transform = frame["cameraTransform"]
    return float(transform[0][3]), float(transform[1][3]), float(transform[2][3])


def launch_ui(
    data_dir: Path,
    recordings: list[Recording],
    observations: list[Observation],
    raw_track: list[TrackPoint],
    smoothed_track: list[TrackPoint],
) -> None:
    import tkinter as tk
    from tkinter import ttk

    start_epoch = min(recording.created_epoch for recording in recordings)
    max_rel = max(recording.created_epoch + recording.frame_times[-1] for recording in recordings) - start_epoch
    track_by_rel = sorted(smoothed_track, key=lambda point: point.rel_t)
    colors = ["#4cc9f0", "#f72585", "#ffd166", "#06d6a0", "#c77dff"]

    root = tk.Tk()
    root.title("Triangometry Drone Map 3D")
    root.geometry("1160x820")
    root.configure(bg="#101214")

    status = tk.StringVar()
    residual_text = "n/a"
    if raw_track:
        residual_text = f"{median([point.residual for point in raw_track]):.2f} m"
    status.set(
        f"raw ARKit map | {len(recordings)} recordings | {len(observations)} observations | "
        f"{len(raw_track)} raw -> {len(smoothed_track)} smooth points | median residual {residual_text}"
    )

    header = ttk.Frame(root, padding=(12, 10, 12, 6))
    header.pack(fill="x")
    ttk.Label(header, textvariable=status).pack(side="left")
    ttk.Button(header, text="Open data", command=lambda: subprocess.run(["open", str(data_dir)], check=False)).pack(
        side="right"
    )

    warning = ttk.Label(
        root,
        text=(
            "RAW debug map: true metric drone coordinates need shared AR world calibration "
            "between the phones."
        ),
        foreground="#f6ad55",
        padding=(12, 0, 12, 8),
    )
    warning.pack(fill="x")

    canvas = tk.Canvas(root, bg="#111820", highlightthickness=0)
    canvas.pack(fill="both", expand=True, padx=12, pady=(0, 8))

    view_controls = ttk.Frame(root, padding=(12, 0, 12, 6))
    view_controls.pack(fill="x")
    yaw_var = tk.DoubleVar(value=-42.0)
    elevation_var = tk.DoubleVar(value=24.0)
    ttk.Label(view_controls, text="Yaw").pack(side="left")
    yaw_slider = ttk.Scale(view_controls, from_=-180.0, to=180.0, orient="horizontal", variable=yaw_var)
    yaw_slider.pack(side="left", fill="x", expand=True, padx=(8, 14))
    ttk.Label(view_controls, text="Elevation").pack(side="left")
    elevation_slider = ttk.Scale(
        view_controls,
        from_=-5.0,
        to=75.0,
        orient="horizontal",
        variable=elevation_var,
    )
    elevation_slider.pack(side="left", fill="x", expand=True, padx=(8, 0))

    slider = ttk.Scale(root, from_=0.0, to=max_rel, orient="horizontal")
    slider.pack(fill="x", padx=12, pady=(0, 8))
    time_label = ttk.Label(root, text="")
    time_label.pack(anchor="w", padx=12, pady=(0, 10))

    all_points: list[tuple[float, float, float]] = []
    for recording in recordings:
        step = max(1, len(recording.frames) // 160)
        for frame in recording.frames[::step]:
            transform = frame["cameraTransform"]
            all_points.append((float(transform[0][3]), float(transform[1][3]), float(transform[2][3])))
    all_points.extend((point.x, point.y, point.z) for point in smoothed_track)
    if not all_points:
        all_points = [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]

    min_x = min(point[0] for point in all_points)
    max_x = max(point[0] for point in all_points)
    min_y = min(point[1] for point in all_points)
    max_y = max(point[1] for point in all_points)
    min_z = min(point[2] for point in all_points)
    max_z = max(point[2] for point in all_points)
    if abs(max_x - min_x) < 1:
        min_x -= 0.5
        max_x += 0.5
    if abs(max_y - min_y) < 1:
        min_y -= 0.5
        max_y += 0.5
    if abs(max_z - min_z) < 1:
        min_z -= 0.5
        max_z += 0.5

    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    center_z = (min_z + max_z) / 2.0
    bbox_corners = [
        (x, y, z)
        for x in (min_x, max_x)
        for y in (min_y, max_y)
        for z in (min_z, max_z)
    ]

    def projected_units(x: float, y: float, z: float) -> tuple[float, float]:
        yaw = math.radians(yaw_var.get())
        elevation = math.radians(elevation_var.get())

        dx = x - center_x
        dy = y - center_y
        dz = z - center_z

        cos_yaw = math.cos(yaw)
        sin_yaw = math.sin(yaw)
        x1 = cos_yaw * dx - sin_yaw * dz
        z1 = sin_yaw * dx + cos_yaw * dz

        cos_elevation = math.cos(elevation)
        sin_elevation = math.sin(elevation)
        y2 = cos_elevation * dy - sin_elevation * z1
        return x1, y2

    def projection_params() -> tuple[float, float, float]:
        width = max(canvas.winfo_width(), 100)
        height = max(canvas.winfo_height(), 100)
        pad = 74
        projected = [projected_units(*corner) for corner in bbox_corners]
        min_px = min(point[0] for point in projected)
        max_px = max(point[0] for point in projected)
        min_py = min(point[1] for point in projected)
        max_py = max(point[1] for point in projected)
        span_x = max(max_px - min_px, 1.0)
        span_y = max(max_py - min_py, 1.0)
        usable_width = max(width - pad * 2, 20)
        usable_height = max(height - pad * 2, 20)
        scale = min(usable_width / span_x, usable_height / span_y)
        return scale, (min_px + max_px) / 2.0, (min_py + max_py) / 2.0

    def world_to_canvas(x: float, y: float, z: float) -> tuple[float, float]:
        width = max(canvas.winfo_width(), 100)
        height = max(canvas.winfo_height(), 100)
        scale, center_px, center_py = projection_params()
        px, py = projected_units(x, y, z)
        return width / 2.0 + (px - center_px) * scale, height / 2.0 - (py - center_py) * scale

    def draw_segment(
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        fill: str,
        width: int = 1,
    ) -> None:
        x0, y0 = world_to_canvas(*start)
        x1, y1 = world_to_canvas(*end)
        canvas.create_line(x0, y0, x1, y1, fill=fill, width=width)

    def draw_polyline(points: list[tuple[float, float, float]], fill: str, width: int, smooth: bool = False) -> None:
        coords: list[float] = []
        for point in points:
            coords.extend(world_to_canvas(*point))
        if len(coords) >= 4:
            canvas.create_line(*coords, fill=fill, width=width, smooth=smooth)

    def draw_grid() -> None:
        for i in range(11):
            ratio = i / 10.0
            x = min_x + (max_x - min_x) * ratio
            z = min_z + (max_z - min_z) * ratio
            draw_segment((x, min_y, min_z), (x, min_y, max_z), "#1e2a32")
            draw_segment((min_x, min_y, z), (max_x, min_y, z), "#1e2a32")

        axis_len = max(max_x - min_x, max_y - min_y, max_z - min_z) * 0.18
        origin = (min_x, min_y, min_z)
        draw_segment(origin, (min_x + axis_len, min_y, min_z), "#ff6b6b", 2)
        draw_segment(origin, (min_x, min_y + axis_len, min_z), "#80ed99", 2)
        draw_segment(origin, (min_x, min_y, min_z + axis_len), "#4cc9f0", 2)
        for label, point, color in (
            ("X", (min_x + axis_len, min_y, min_z), "#ffb3b3"),
            ("Y", (min_x, min_y + axis_len, min_z), "#b7f7c8"),
            ("Z", (min_x, min_y, min_z + axis_len), "#a8e7ff"),
        ):
            lx, ly = world_to_canvas(*point)
            canvas.create_text(lx + 8, ly, text=label, fill=color, anchor="w", font=("Menlo", 11, "bold"))

    def draw() -> None:
        rel_t = float(slider.get())
        canvas.delete("all")
        draw_grid()
        time_label.config(text=f"t = {rel_t:05.2f}s | yaw {yaw_var.get():.0f} | elevation {elevation_var.get():.0f}")

        for idx, recording in enumerate(recordings):
            color = colors[idx % len(colors)]
            step = max(1, len(recording.frames) // 240)
            points = []
            for frame in recording.frames[::step]:
                transform = frame["cameraTransform"]
                points.append((float(transform[0][3]), float(transform[1][3]), float(transform[2][3])))
            draw_polyline(points, fill=color, width=2, smooth=True)
            px, py, pz = recording_position_at(recording, rel_t, start_epoch)
            cx, cz = world_to_canvas(px, py, pz)
            canvas.create_oval(cx - 6, cz - 6, cx + 6, cz + 6, fill=color, outline="")
            canvas.create_text(cx + 10, cz - 12, text=recording.device, fill=color, anchor="w", font=("Menlo", 11))

        if track_by_rel:
            trail: list[tuple[float, float, float]] = []
            for point in track_by_rel:
                if point.rel_t > rel_t:
                    break
                trail.append((point.x, point.y, point.z))
            draw_polyline(trail, fill="#ffffff", width=3, smooth=True)
            current = min(track_by_rel, key=lambda point: abs(point.rel_t - rel_t))
            dx, dz = world_to_canvas(current.x, current.y, current.z)
            canvas.create_oval(dx - 7, dz - 7, dx + 7, dz + 7, fill="#ffffff", outline="#ffbe0b", width=3)
            canvas.create_text(
                dx + 12,
                dz + 10,
                text=(
                    f"drone smooth\n"
                    f"x {current.x:.1f} y {current.y:.1f} z {current.z:.1f}\n"
                    f"res {current.residual:.1f}m"
                ),
                fill="#e8f1f8",
                anchor="nw",
                font=("Menlo", 11),
            )
        else:
            canvas.create_text(
                canvas.winfo_width() / 2,
                canvas.winfo_height() / 2,
                text="No triangulated drone track.\nNeed at least two synchronized observations in a shared AR world.",
                fill="#e8f1f8",
                justify="center",
                font=("Menlo", 14),
            )

    slider.configure(command=lambda _value: draw())
    yaw_slider.configure(command=lambda _value: draw())
    elevation_slider.configure(command=lambda _value: draw())
    canvas.bind("<Configure>", lambda _event: draw())
    root.after(50, draw)
    root.mainloop()


def analyze(args: argparse.Namespace) -> tuple[list[Recording], list[Observation], list[TrackPoint], list[TrackPoint]]:
    data_dir = Path(args.data).expanduser().resolve()
    rendered_arg = Path(args.rendered_dir).expanduser()
    rendered_dir = rendered_arg
    if not rendered_dir.is_absolute():
        rendered_dir = rendered_arg.resolve() if rendered_arg.exists() else data_dir / rendered_arg

    recordings = load_recordings(data_dir)
    if not recordings:
        raise SystemExit(f"no recordings found in {data_dir}")

    observation_mode = "rendered"
    observations = load_rendered_observations(
        recordings=recordings,
        rendered_dir=rendered_dir,
        include_taps=True,
    )
    rendered_count = sum(1 for obs in observations if obs.source == "rendered")
    write_observations(data_dir / "drone_observations_rendered.csv", observations)

    if rendered_count == 0 and args.use_video_detection:
        observation_mode = "video-detection"
        observations = detect_observations(
            recordings=recordings,
            data_dir=data_dir,
            sample_fps=args.fps,
            width=args.width,
            force=args.force,
        )
    elif rendered_count == 0:
        print(
            "no rendered observations loaded; pass --use-video-detection to run the slow video fallback",
            file=sys.stderr,
        )

    raw_track = build_track(recordings, observations, bin_seconds=args.bin_seconds)
    if args.no_smoothing:
        smoothed_track = raw_track
    else:
        smoothed_track = smooth_track(
            raw_track,
            step_seconds=args.smooth_step,
            max_speed=args.smooth_max_speed,
            alpha=args.smooth_alpha,
            measurement_gap_seconds=args.smooth_gap,
            median_window_seconds=args.smooth_window,
            residual_gate=args.smooth_residual_gate,
            max_acceleration=args.smooth_max_accel,
        )

    write_track_csv(data_dir / "drone_track_raw.csv", raw_track)
    write_track_csv(data_dir / "drone_track_smooth.csv", smoothed_track)
    write_summary_json(
        data_dir / "drone_analysis_summary.json",
        recordings,
        observations,
        raw_track,
        smoothed_track,
        observation_mode=observation_mode,
        bin_seconds=args.bin_seconds,
        rendered_dir=rendered_dir,
        smoothing_enabled=not args.no_smoothing,
        smooth_step_seconds=args.smooth_step,
        smooth_max_speed=args.smooth_max_speed,
        smooth_alpha=args.smooth_alpha,
        smooth_measurement_gap_seconds=args.smooth_gap,
        smooth_median_window_seconds=args.smooth_window,
        smooth_residual_gate=args.smooth_residual_gate,
        smooth_max_acceleration=args.smooth_max_accel,
    )
    return recordings, observations, raw_track, smoothed_track


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Triangometry recordings and show a drone map.")
    parser.add_argument("--data", default="data", help="directory containing .mov + *_metadata.json files")
    parser.add_argument(
        "--rendered-dir",
        default="rendered",
        help="directory containing *_coordinates.json files; defaults to rendered/ under --data",
    )
    parser.add_argument("--fps", type=float, default=2.0, help="video analysis sample rate")
    parser.add_argument("--width", type=int, default=480, help="scaled video width for blob detection")
    parser.add_argument("--bin-seconds", type=float, default=0.05, help="time bin for multi-camera matching")
    parser.add_argument("--smooth-step", type=float, default=0.05, help="output timestep for the smoothed track")
    parser.add_argument(
        "--smooth-max-speed",
        type=float,
        default=5.0,
        help="maximum smoothed drone speed in ARKit meters per second",
    )
    parser.add_argument("--smooth-alpha", type=float, default=0.55, help="measurement pull strength for smoothing")
    parser.add_argument(
        "--smooth-gap",
        type=float,
        default=0.16,
        help="maximum time distance from a raw point before the smoother predicts through a gap",
    )
    parser.add_argument(
        "--smooth-window",
        type=float,
        default=0.75,
        help="median-filter window in seconds before velocity smoothing",
    )
    parser.add_argument(
        "--smooth-residual-gate",
        type=float,
        default=15.0,
        help="ignore raw points above this residual while building median measurements",
    )
    parser.add_argument(
        "--smooth-max-accel",
        type=float,
        default=8.0,
        help="maximum acceleration in ARKit meters per second squared",
    )
    parser.add_argument("--no-smoothing", action="store_true", help="show and export the unsmoothed raw track")
    parser.add_argument("--force", action="store_true", help="rebuild cached detections")
    parser.add_argument(
        "--use-video-detection",
        action="store_true",
        help="fallback to slow ffmpeg dark-blob detection when rendered coordinates are missing",
    )
    parser.add_argument("--no-ui", action="store_true", help="only write CSV/JSON outputs")
    args = parser.parse_args()

    start = time.time()
    recordings, observations, raw_track, smoothed_track = analyze(args)
    print(
        f"recordings={len(recordings)} observations={len(observations)} "
        f"raw_track_points={len(raw_track)} smooth_track_points={len(smoothed_track)} "
        f"elapsed={time.time() - start:.1f}s"
    )
    if raw_track:
        print(f"median raw residual={median([point.residual for point in raw_track]):.2f} m")
        print("wrote data/drone_track_raw.csv, data/drone_track_smooth.csv and data/drone_analysis_summary.json")
    else:
        print("no track written: need at least two observations in the same time bin")

    if not args.no_ui:
        launch_ui(Path(args.data).expanduser().resolve(), recordings, observations, raw_track, smoothed_track)


if __name__ == "__main__":
    main()
