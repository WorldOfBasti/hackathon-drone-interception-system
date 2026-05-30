#!/usr/bin/env python3
"""WebGL 3D viewer for Triangometry drone tracks.

This keeps Python as the entrypoint and uses Three.js from a CDN in the
browser. No Python visualization packages are required.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import drone_map_ui


COLORS = ["#0077b6", "#d0006f", "#b7791f", "#008f5a", "#7b2cbf"]
TOWER_SVG = (Path(__file__).resolve().parent / "icons" / "tower.svg").read_text(encoding="utf-8")
DRONE_SVG = (Path(__file__).resolve().parent / "icons" / "drone.svg").read_text(encoding="utf-8")


def frame_position(frame: dict) -> list[float]:
    transform = frame["cameraTransform"]
    return [float(transform[0][3]), float(transform[1][3]), float(transform[2][3])]


def track_point(point: drone_map_ui.TrackPoint) -> dict:
    return {
        "t": point.rel_t,
        "global_t": point.global_t,
        "x": point.x,
        "y": point.y,
        "z": point.z,
        "residual": point.residual,
        "devices": point.devices,
    }


def recording_scene(recording: drone_map_ui.Recording, color: str) -> dict:
    path = []
    for frame in recording.frames:
        x, y, z = frame_position(frame)
        path.append(
            {
                "t": recording.created_epoch
                + float(frame["videoPresentationTime"]),
                "video_t": float(frame["videoPresentationTime"]),
                "x": x,
                "y": y,
                "z": z,
            }
        )

    return {
        "device": recording.device,
        "base": recording.base,
        "color": color,
        "created_epoch": recording.created_epoch,
        "duration": recording.frame_times[-1],
        "path": path,
    }


def scene_bounds(scene_points: list[list[float]]) -> dict:
    if not scene_points:
        scene_points = [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]

    mins = [min(point[idx] for point in scene_points) for idx in range(3)]
    maxs = [max(point[idx] for point in scene_points) for idx in range(3)]
    for idx in range(3):
        if abs(maxs[idx] - mins[idx]) < 1.0:
            mins[idx] -= 0.5
            maxs[idx] += 0.5

    center = [(mins[idx] + maxs[idx]) / 2.0 for idx in range(3)]
    radius = max(
        sum((point[idx] - center[idx]) ** 2 for idx in range(3)) ** 0.5
        for point in scene_points
    )
    return {"min": mins, "max": maxs, "center": center, "radius": max(radius, 1.0)}


def load_summary(data_dir: Path) -> dict:
    path = data_dir / "drone_analysis_summary.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def build_scene(args: argparse.Namespace) -> dict:
    analysis_args = SimpleNamespace(
        data=args.data,
        rendered_dir=args.rendered_dir,
        fps=args.fps,
        width=args.width,
        bin_seconds=args.bin_seconds,
        smooth_step=args.smooth_step,
        smooth_max_speed=args.smooth_max_speed,
        smooth_alpha=args.smooth_alpha,
        smooth_gap=args.smooth_gap,
        smooth_window=args.smooth_window,
        smooth_residual_gate=args.smooth_residual_gate,
        smooth_max_accel=args.smooth_max_accel,
        no_smoothing=args.no_smoothing,
        force=args.force,
        use_video_detection=args.use_video_detection,
    )
    recordings, observations, raw_track, smooth_track = drone_map_ui.analyze(analysis_args)

    data_dir = Path(args.data).expanduser().resolve()
    recording_payloads = [
        recording_scene(recording, COLORS[idx % len(COLORS)])
        for idx, recording in enumerate(recordings)
    ]
    raw_payload = [track_point(point) for point in raw_track]
    smooth_payload = [track_point(point) for point in smooth_track]

    all_points: list[list[float]] = []
    for recording in recording_payloads:
        step = max(1, len(recording["path"]) // 700)
        all_points.extend([point["x"], point["y"], point["z"]] for point in recording["path"][::step])
    all_points.extend([point["x"], point["y"], point["z"]] for point in smooth_payload)

    scene = {
        "title": "Triangometry Drone Track",
        "warning": (
            "Raw ARKit debug map. True metric multi-phone coordinates need shared-world calibration."
        ),
        "recordings": recording_payloads,
        "raw_track": raw_payload,
        "smooth_track": smooth_payload,
        "observations": len(observations),
        "summary": load_summary(data_dir),
        "bounds": scene_bounds(all_points),
    }

    scene_path = data_dir / "drone_scene_3d.json"
    with scene_path.open("w", encoding="utf-8") as handle:
        json.dump(scene, handle)
        handle.write("\n")
    return scene


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Triangometry Drone Track 3D</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: rgba(255, 255, 255, 0.76);
      --button: rgba(255, 255, 255, 0.64);
      --button-hover: rgba(255, 255, 255, 0.92);
      --line: rgba(25, 39, 57, 0.16);
      --text: #111827;
      --muted: #5f7287;
      --accent: #009fe3;
      --warning: #9a5a00;
      --shadow: rgba(29, 45, 68, 0.16);
    }
    body[data-theme="dark"] {
      color-scheme: dark;
      --bg: #05070a;
      --panel: rgba(11, 16, 22, 0.74);
      --button: rgba(255, 255, 255, 0.08);
      --button-hover: rgba(255, 255, 255, 0.14);
      --line: rgba(255, 255, 255, 0.14);
      --text: #edf6ff;
      --muted: #9fb3c8;
      --warning: #ffd166;
      --shadow: rgba(0, 0, 0, 0.34);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      overflow: hidden;
      background: var(--bg);
      color: var(--text);
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }
    #scene {
      position: fixed;
      inset: 0;
    }
    .hud {
      position: fixed;
      left: 14px;
      top: 14px;
      display: grid;
      gap: 8px;
      width: min(480px, calc(100vw - 28px));
      pointer-events: none;
    }
    .panel {
      pointer-events: auto;
      border: 1px solid var(--line);
      background: var(--panel);
      backdrop-filter: blur(14px);
      border-radius: 10px;
      box-shadow: 0 16px 48px var(--shadow);
    }
    .stats {
      padding: 12px 14px;
    }
    .title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      font-size: 14px;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }
    .pill {
      color: #101014;
      background: var(--accent);
      border-radius: 999px;
      padding: 3px 8px;
      font-size: 11px;
      font-weight: 800;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;
    }
    .metric {
      border-top: 1px solid var(--line);
      padding-top: 8px;
      min-width: 0;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .metric strong {
      display: block;
      margin-top: 4px;
      font-size: 15px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .warn {
      color: var(--warning);
      font-size: 12px;
      line-height: 1.35;
      padding: 10px 14px;
    }
    .controls {
      position: fixed;
      left: 14px;
      right: 14px;
      bottom: 14px;
      display: grid;
      grid-template-columns: auto auto 1fr auto auto;
      align-items: center;
      gap: 12px;
      padding: 12px;
    }
    button {
      border: 1px solid var(--line);
      background: var(--button);
      color: var(--text);
      border-radius: 8px;
      height: 36px;
      padding: 0 12px;
      font: inherit;
      cursor: pointer;
    }
    button:hover { background: var(--button-hover); }
    input[type="range"] {
      width: 100%;
      accent-color: var(--accent);
    }
    .time {
      color: var(--muted);
      min-width: 86px;
      text-align: right;
    }
    .legend {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
    }
    .dot {
      display: inline-block;
      width: 9px;
      height: 9px;
      border-radius: 999px;
      margin-right: 5px;
      vertical-align: -1px;
    }
    @media (max-width: 760px) {
      .hud { width: calc(100vw - 28px); }
      .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .controls { grid-template-columns: auto auto 1fr auto; }
      .legend { display: none; }
    }
  </style>
  <script type="importmap">
    {
      "imports": {
        "three": "https://cdn.jsdelivr.net/npm/three@0.164.1/build/three.module.js",
        "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.164.1/examples/jsm/"
      }
    }
  </script>
</head>
<body data-theme="light">
  <div id="scene"></div>
  <div class="hud">
    <section class="panel stats">
      <div class="title">
        <strong>Triangometry 3D</strong>
        <span class="pill">WebGL</span>
      </div>
      <div class="grid">
        <div class="metric"><span>Recordings</span><strong id="recordings">-</strong></div>
        <div class="metric"><span>Observations</span><strong id="observations">-</strong></div>
        <div class="metric"><span>Smooth pts</span><strong id="smooth-points">-</strong></div>
        <div class="metric"><span>Residual</span><strong id="residual">-</strong></div>
        <div class="metric"><span>X</span><strong id="coord-x">-</strong></div>
        <div class="metric"><span>Y</span><strong id="coord-y">-</strong></div>
        <div class="metric"><span>Z</span><strong id="coord-z">-</strong></div>
        <div class="metric"><span>Devices</span><strong id="devices">-</strong></div>
      </div>
    </section>
    <section class="panel warn" id="warning"></section>
  </div>
  <section class="panel controls">
    <button id="play">Play</button>
    <button id="theme-toggle">Dark</button>
    <input id="timeline" type="range" min="0" max="1" value="0" step="0.05" />
    <div class="time" id="time">t 0.00s</div>
    <div class="legend" id="legend"></div>
  </section>

	  <script type="module">
	    import * as THREE from 'three';
	    import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
	
	    const sceneData = await fetch('/scene.json').then((response) => response.json());
	    const container = document.getElementById('scene');
	    const towerSvgSource = __TOWER_SVG__;
	    const droneSvgSource = __DRONE_SVG__;
	    function svgViewBox(svgSource, fallback = '0 0 25 25') {
	      const svgDoc = new DOMParser().parseFromString(svgSource, 'image/svg+xml');
	      return (svgDoc.documentElement.getAttribute('viewBox') || fallback)
	        .trim()
	        .split(/\s+/)
	        .map(Number);
	    }

	    function svgDataUrl(svgSource) {
	      return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgSource)}`;
	    }

	    async function loadSvgIcon(svgSource) {
	      const image = new Image();
	      const url = svgDataUrl(svgSource);
	      const loaded = new Promise((resolve, reject) => {
	        image.onload = resolve;
	        image.onerror = reject;
	      });
	      image.src = url;
	      await loaded;
	      return { image, url, viewBox: svgViewBox(svgSource) };
	    }

	    const towerSvgIcon = await loadSvgIcon(towerSvgSource);
	    const droneSvgIcon = await loadSvgIcon(droneSvgSource);
	    const stationTowerColor = '#009fe3';
	    const droneTowerColor = '#e30613';

	    function towerLabel(index) {
	      return `Tower ${String(index + 1).padStart(2, '0')}`;
	    }

    function hasWebGL() {
      try {
        const canvas = document.createElement('canvas');
        return Boolean(
          canvas.getContext('webgl2') ||
          canvas.getContext('webgl') ||
          canvas.getContext('experimental-webgl')
        );
      } catch (_error) {
        return false;
      }
    }

    function startCanvasFallback(reason) {
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      container.appendChild(canvas);

      const smooth = sceneData.smooth_track;
      const bounds = sceneData.bounds;
      const center = bounds.center;
      const radius = bounds.radius;
      const groundY = bounds.min[1];
      const sceneStartEpoch = Math.min(...sceneData.recordings.map((recording) => recording.created_epoch));
      const minT = smooth.length ? smooth[0].t : 0;
      const maxT = smooth.length ? smooth[smooth.length - 1].t : 1;
      const timeline = document.getElementById('timeline');
      const timeLabel = document.getElementById('time');
      const playButton = document.getElementById('play');
      const themeToggle = document.getElementById('theme-toggle');
      const warning = document.getElementById('warning');
      const fallbackNote = reason ? ` Canvas fallback active: ${reason}` : ' Canvas fallback active.';

      let currentTheme = 'light';
      let playing = true;
      let currentT = minT;
      let lastFrame = performance.now();
      const playbackSpeed = 1.6;

      timeline.min = minT.toFixed(2);
      timeline.max = maxT.toFixed(2);
      timeline.step = '0.05';
      timeline.value = minT.toFixed(2);
      document.getElementById('recordings').textContent = sceneData.recordings.length;
      document.getElementById('observations').textContent = sceneData.observations;
      document.getElementById('smooth-points').textContent = smooth.length;
      warning.textContent = sceneData.warning + fallbackNote;
      playButton.textContent = 'Pause';

	      function colors() {
	        return currentTheme === 'light'
	          ? { bg: '#f6f8fb', grid: '#d6e1ea', gridStrong: '#8fa8bb', text: '#111827', trail: '#1d4ed8', drone: droneTowerColor, drop: droneTowerColor, vector: 'rgba(227, 6, 19, 0.55)', shadow: 'rgba(17, 24, 39, 0.34)' }
	          : { bg: '#05070a', grid: '#17232c', gridStrong: '#2d4453', text: '#edf6ff', trail: '#fff2a8', drone: droneTowerColor, drop: droneTowerColor, vector: 'rgba(255, 122, 142, 0.68)', shadow: 'rgba(0, 0, 0, 0.62)' };
	      }

      function resize() {
        canvas.width = Math.floor(window.innerWidth * window.devicePixelRatio);
        canvas.height = Math.floor(window.innerHeight * window.devicePixelRatio);
        canvas.style.width = `${window.innerWidth}px`;
        canvas.style.height = `${window.innerHeight}px`;
        ctx.setTransform(window.devicePixelRatio, 0, 0, window.devicePixelRatio, 0, 0);
      }

      function project(x, y, z) {
        const yaw = -0.72;
        const elevation = 0.52;
        const dx = x - center[0];
        const dy = y - center[1];
        const dz = z - center[2];
        const x1 = Math.cos(yaw) * dx - Math.sin(yaw) * dz;
        const z1 = Math.sin(yaw) * dx + Math.cos(yaw) * dz;
        const y2 = Math.cos(elevation) * dy - Math.sin(elevation) * z1;
        const scale = Math.min(window.innerWidth, window.innerHeight) / Math.max(radius * 2.25, 1);
        return [window.innerWidth / 2 + x1 * scale, window.innerHeight / 2 - y2 * scale];
      }

      function nearestIndex(points, relT) {
        if (!points.length) return -1;
        let lo = 0;
        let hi = points.length - 1;
        while (lo < hi) {
          const mid = Math.floor((lo + hi) / 2);
          if (points[mid].t < relT) lo = mid + 1;
          else hi = mid;
        }
        if (lo > 0 && Math.abs(points[lo - 1].t - relT) < Math.abs(points[lo].t - relT)) return lo - 1;
        return lo;
      }

	    function nearestPathPoint(path, relT, recording) {
	      if (!path.length) return null;
	      const globalT = sceneStartEpoch + relT;
        let best = path[0];
        let bestDistance = Math.abs(recording.created_epoch + best.video_t - globalT);
        const step = Math.max(1, Math.floor(path.length / 240));
        for (let i = 1; i < path.length; i += step) {
          const distance = Math.abs(recording.created_epoch + path[i].video_t - globalT);
          if (distance < bestDistance) {
            best = path[i];
            bestDistance = distance;
          }
        }
	      return best;
	    }

	      function drawLine(points, color, width, stride = 1, limit = points.length) {
	        ctx.beginPath();
	        let started = false;
        for (let i = 0; i < Math.min(points.length, limit); i += stride) {
          const point = points[i];
          const [x, y] = project(point.x, point.y, point.z);
          if (!started) {
            ctx.moveTo(x, y);
            started = true;
          } else {
            ctx.lineTo(x, y);
          }
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = width;
        ctx.lineCap = 'round';
	        ctx.lineJoin = 'round';
	        ctx.stroke();
	      }

	      function drawSvgIcon(icon, x, y, size) {
	        const [_minX, _minY, width, height] = icon.viewBox;
	        const scale = size / Math.max(width, height);
	        const drawWidth = width * scale;
	        const drawHeight = height * scale;
	        ctx.drawImage(icon.image, x - drawWidth / 2, y - drawHeight / 2, drawWidth, drawHeight);
	      }

	      function shadowRadiusForAltitude(altitude, minRadius, maxRadius) {
	        const normalized = Math.min(Math.max(altitude / Math.max(radius * 0.72, 1), 0), 1.35);
	        return minRadius + (maxRadius - minRadius) * normalized;
	      }

	      function drawDroneShadow(gx, gy, altitude, palette) {
	        const shadowRadius = shadowRadiusForAltitude(altitude, 22, 74);
	        const gradient = ctx.createRadialGradient(gx, gy, 0, gx, gy, shadowRadius);
	        gradient.addColorStop(0, palette.shadow);
	        gradient.addColorStop(0.58, palette.shadow);
	        gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
	        ctx.save();
	        ctx.fillStyle = gradient;
	        ctx.beginPath();
	        ctx.arc(gx, gy, shadowRadius, 0, Math.PI * 2);
	        ctx.fill();
	        ctx.restore();
	      }

	      function drawGrid(palette) {
	        const minX = bounds.min[0], maxX = bounds.max[0];
        const minZ = bounds.min[2], maxZ = bounds.max[2];
        ctx.lineWidth = 1;
        for (let i = 0; i <= 12; i++) {
          const ratio = i / 12;
          const x = minX + (maxX - minX) * ratio;
          const z = minZ + (maxZ - minZ) * ratio;
          const [x0, y0] = project(x, groundY, minZ);
          const [x1, y1] = project(x, groundY, maxZ);
          const [x2, y2] = project(minX, groundY, z);
          const [x3, y3] = project(maxX, groundY, z);
          ctx.strokeStyle = i % 3 === 0 ? palette.gridStrong : palette.grid;
          ctx.beginPath();
          ctx.moveTo(x0, y0);
          ctx.lineTo(x1, y1);
          ctx.moveTo(x2, y2);
          ctx.lineTo(x3, y3);
          ctx.stroke();
        }
      }

	      function drawCurrent(relT) {
	        const palette = colors();
	        ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
	        ctx.fillStyle = palette.bg;
	        ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);
	        drawGrid(palette);
	        const idx = nearestIndex(smooth, relT);
	        const current = idx >= 0 ? smooth[idx] : null;

	        for (const recording of sceneData.recordings) {
	          const stride = Math.max(1, Math.floor(recording.path.length / 700));
	          drawLine(recording.path, recording.color, 2, stride);
	        }

	        if (current) {
	          drawLine(smooth, palette.trail, 4, 1, idx + 1);
	          const [x, y] = project(current.x, current.y, current.z);
	          const [gx, gy] = project(current.x, groundY, current.z);
	          drawDroneShadow(gx, gy, Math.max(0, current.y - groundY), palette);
	          ctx.save();
	          ctx.strokeStyle = palette.vector;
	          ctx.lineWidth = 4.2;
	          ctx.lineCap = 'round';
	          ctx.setLineDash([16, 10]);
	          for (const recording of sceneData.recordings) {
	            const point = nearestPathPoint(recording.path, relT, recording);
	            if (!point) continue;
	            const [tx, ty] = project(point.x, point.y, point.z);
	            ctx.beginPath();
	            ctx.moveTo(tx, ty);
	            ctx.lineTo(x, y);
	            ctx.stroke();
	          }
	          ctx.restore();
	          ctx.strokeStyle = palette.drop;
	          ctx.lineWidth = 1.5;
	          ctx.beginPath();
	          ctx.moveTo(x, y);
		          ctx.lineTo(gx, gy);
		          ctx.stroke();
	        }

	        for (const [recordingIndex, recording] of sceneData.recordings.entries()) {
	          const point = nearestPathPoint(recording.path, relT, recording);
	          if (!point) continue;
	          const [x, y] = project(point.x, point.y, point.z);
	          drawSvgIcon(towerSvgIcon, x, y, 28);
	          const label = towerLabel(recordingIndex);
	          ctx.font = '700 18px Menlo, monospace';
	          ctx.lineWidth = 5;
	          ctx.strokeStyle = currentTheme === 'light' ? 'rgba(246, 248, 251, 0.92)' : 'rgba(5, 7, 10, 0.9)';
	          ctx.strokeText(label, x + 14, y - 16);
	          ctx.fillStyle = stationTowerColor;
	          ctx.fillText(label, x + 14, y - 16);
	        }

	        if (current) {
	          const [x, y] = project(current.x, current.y, current.z);
	          drawSvgIcon(droneSvgIcon, x, y, 34);

	          document.getElementById('coord-x').textContent = current.x.toFixed(2);
	          document.getElementById('coord-y').textContent = current.y.toFixed(2);
          document.getElementById('coord-z').textContent = current.z.toFixed(2);
          document.getElementById('residual').textContent = `${current.residual.toFixed(2)} m`;
          document.getElementById('devices').textContent = current.devices.join('+') || '-';
        }
        timeLabel.textContent = `t ${relT.toFixed(2)}s`;
        timeline.value = relT.toFixed(2);
      }

      playButton.addEventListener('click', () => {
        playing = !playing;
        playButton.textContent = playing ? 'Pause' : 'Play';
      });
      themeToggle.addEventListener('click', () => {
        currentTheme = currentTheme === 'light' ? 'dark' : 'light';
        document.body.dataset.theme = currentTheme;
        themeToggle.textContent = currentTheme === 'light' ? 'Dark' : 'Light';
        drawCurrent(currentT);
      });
      timeline.addEventListener('input', () => {
        currentT = Number(timeline.value);
        playing = false;
        playButton.textContent = 'Play';
        drawCurrent(currentT);
      });
      window.addEventListener('resize', () => {
        resize();
        drawCurrent(currentT);
      });

      resize();
      drawCurrent(currentT);
      function animate(now) {
        const dt = Math.min((now - lastFrame) / 1000, 0.08);
        lastFrame = now;
        if (playing && smooth.length) {
          currentT += dt * playbackSpeed;
          if (currentT > maxT) currentT = minT;
          drawCurrent(currentT);
        }
        requestAnimationFrame(animate);
      }
      requestAnimationFrame(animate);
    }

    if (!hasWebGL()) {
      startCanvasFallback('WebGL is unavailable in this browser session.');
    } else {
    const themes = {
      light: {
        background: 0xf6f8fb,
        fog: 0xf6f8fb,
        fogDensity: 0.0028,
        gridMajor: 0x8fa8bb,
        gridMinor: 0xd6e1ea,
	        fullTube: 0x6b7280,
	        trail: 0x1d4ed8,
		        drone: 0xe30613,
		        drop: 0xe30613,
	        vector: 0xe30613,
	        vectorOpacity: 0.62,
	        shadow: 0x111827,
	        shadowOpacity: 0.46,
	        ambient: 0xffffff,
	        ambientIntensity: 0.82,
	        sun: 0xffffff,
        sunIntensity: 1.35,
      },
      dark: {
        background: 0x05070a,
        fog: 0x05070a,
        fogDensity: 0.008,
        gridMajor: 0x2d4453,
        gridMinor: 0x17232c,
	        fullTube: 0xffffff,
	        trail: 0xfff2a8,
		        drone: 0xe30613,
		        drop: 0xe30613,
	        vector: 0xff7a8e,
	        vectorOpacity: 0.76,
	        shadow: 0x000000,
	        shadowOpacity: 0.68,
	        ambient: 0xffffff,
	        ambientIntensity: 0.55,
        sun: 0xffffff,
        sunIntensity: 1.25,
      },
    };
    let currentTheme = 'light';
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(themes.light.background);
    scene.fog = new THREE.FogExp2(themes.light.fog, themes.light.fogDensity);

    const bounds = sceneData.bounds;
    const center = new THREE.Vector3(...bounds.center);
    const radius = bounds.radius;

    const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.01, radius * 20);
    camera.position.set(center.x + radius * 1.35, center.y + radius * 0.78, center.z + radius * 1.3);
    camera.lookAt(center);

    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch (error) {
      startCanvasFallback('WebGL context creation failed.');
      throw error;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(center);
    controls.enableDamping = true;
    controls.dampingFactor = 0.075;
    controls.maxDistance = radius * 8;
    controls.minDistance = radius * 0.12;

    const ambient = new THREE.AmbientLight(themes.light.ambient, themes.light.ambientIntensity);
    scene.add(ambient);
    const sun = new THREE.DirectionalLight(themes.light.sun, themes.light.sunIntensity);
    sun.position.set(center.x + radius * 0.6, center.y + radius * 1.5, center.z + radius * 0.8);
    scene.add(sun);

    const groundY = bounds.min[1];
    const gridSize = Math.max(bounds.max[0] - bounds.min[0], bounds.max[2] - bounds.min[2], 1) * 1.18;
    const grid = new THREE.GridHelper(gridSize, 22, themes.light.gridMajor, themes.light.gridMinor);
    grid.position.set(center.x, groundY, center.z);
    scene.add(grid);

    const axes = new THREE.AxesHelper(radius * 0.18);
    axes.position.set(bounds.min[0], groundY, bounds.min[2]);
    scene.add(axes);

    function vectorFromPoint(point) {
      return new THREE.Vector3(point.x, point.y, point.z);
    }

    function makeLine(points, color, opacity = 1, stride = 1) {
      const sampled = [];
      for (let i = 0; i < points.length; i += stride) sampled.push(vectorFromPoint(points[i]));
      if (sampled.length < 2) return null;
      const geometry = new THREE.BufferGeometry().setFromPoints(sampled);
      const material = new THREE.LineBasicMaterial({
        color,
        transparent: opacity < 1,
        opacity,
      });
      return new THREE.Line(geometry, material);
    }

    function makeTube(points, color, opacity, tubeRadius) {
      if (points.length < 2) return null;
      const vectors = points.map(vectorFromPoint);
      const curve = new THREE.CatmullRomCurve3(vectors, false, 'catmullrom', 0.2);
      const geometry = new THREE.TubeGeometry(curve, Math.min(points.length * 2, 3000), tubeRadius, 8, false);
      const material = new THREE.MeshStandardMaterial({
        color,
        emissive: color,
        emissiveIntensity: 0.18,
        roughness: 0.42,
        metalness: 0.0,
        transparent: opacity < 1,
        opacity,
      });
      return new THREE.Mesh(geometry, material);
    }

	    function makeLabel(text, color) {
	      const canvas = document.createElement('canvas');
	      canvas.width = 384;
	      canvas.height = 112;
      const ctx = canvas.getContext('2d');
      ctx.font = '800 44px Menlo, monospace';
      ctx.fillStyle = 'rgba(255, 255, 255, 0.84)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = color;
      ctx.fillText(text, 18, 72);
      const texture = new THREE.CanvasTexture(canvas);
      const material = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        depthWrite: false,
        depthTest: false,
      });
      const sprite = new THREE.Sprite(material);
	      sprite.renderOrder = 56;
	      sprite.scale.set(radius * 0.32, radius * 0.094, 1);
	      return sprite;
	    }

	    function textureFromSvgIcon(icon) {
	      const [_minX, _minY, width, height] = icon.viewBox;
	      const resolution = 10;
	      const canvas = document.createElement('canvas');
	      canvas.width = Math.ceil(width * resolution);
	      canvas.height = Math.ceil(height * resolution);
	      const ctx = canvas.getContext('2d');
	      ctx.drawImage(icon.image, 0, 0, canvas.width, canvas.height);
	      const texture = new THREE.CanvasTexture(canvas);
	      texture.colorSpace = THREE.SRGBColorSpace;
	      texture.minFilter = THREE.LinearFilter;
	      texture.magFilter = THREE.LinearFilter;
	      texture.needsUpdate = true;
	      return texture;
	    }

	    const towerTexture = textureFromSvgIcon(towerSvgIcon);
	    const droneTexture = textureFromSvgIcon(droneSvgIcon);

	    function makeSvgSprite(icon, texture, size) {
	      const [_minX, _minY, width, height] = icon.viewBox;
	      const scale = size / Math.max(width, height);
	      const sprite = new THREE.Sprite(
	        new THREE.SpriteMaterial({
	          map: texture,
	          transparent: true,
	          depthWrite: false,
	          alphaTest: 0.01,
	        }),
	      );
	      sprite.scale.set(width * scale, height * scale, 1);
	      return sprite;
	    }

	    function makeShadowTexture() {
	      const canvas = document.createElement('canvas');
	      canvas.width = 256;
	      canvas.height = 256;
	      const ctx = canvas.getContext('2d');
	      const gradient = ctx.createRadialGradient(128, 128, 0, 128, 128, 118);
	      gradient.addColorStop(0, 'rgba(0, 0, 0, 0.9)');
	      gradient.addColorStop(0.45, 'rgba(0, 0, 0, 0.48)');
	      gradient.addColorStop(1, 'rgba(0, 0, 0, 0)');
	      ctx.fillStyle = gradient;
	      ctx.fillRect(0, 0, canvas.width, canvas.height);
	      const texture = new THREE.CanvasTexture(canvas);
	      texture.colorSpace = THREE.SRGBColorSpace;
	      texture.needsUpdate = true;
	      return texture;
	    }

	    function faceCamera(_object) {}
	
	    const legend = document.getElementById('legend');
	    const cameraMarkers = [];
    for (const [idx, recording] of sceneData.recordings.entries()) {
      const stride = Math.max(1, Math.floor(recording.path.length / 900));
      const line = makeLine(recording.path, recording.color, 0.88, stride);
      if (line) scene.add(line);

	      const marker = makeSvgSprite(towerSvgIcon, towerTexture, Math.max(radius * 0.12, 1.2));
	      const labelText = towerLabel(idx);
	      const label = makeLabel(labelText, stationTowerColor);
	      scene.add(marker, label);
	      cameraMarkers.push({ recording, marker, label });

      const item = document.createElement('span');
      item.innerHTML = `<span class="dot" style="background:${stationTowerColor}"></span>${labelText}`;
      legend.appendChild(item);
    }

    const smooth = sceneData.smooth_track;
    const raw = sceneData.raw_track;
    const tubeRadius = Math.max(radius * 0.0035, 0.025);
    const fullTube = makeTube(smooth, themes.light.fullTube, 0.28, tubeRadius);
    if (fullTube) scene.add(fullTube);

	    const trailGeo = new THREE.BufferGeometry().setFromPoints(smooth.map(vectorFromPoint));
	    trailGeo.setDrawRange(0, 1);
	    const trailMat = new THREE.LineBasicMaterial({ color: themes.light.trail, transparent: true, opacity: 0.96 });
	    const trail = new THREE.Line(trailGeo, trailMat);
	    scene.add(trail);

	    const vectorDashGeometry = new THREE.CylinderGeometry(1, 1, 1, 12, 1, true);
	    const vectorMat = new THREE.MeshBasicMaterial({
	      color: themes.light.vector,
	      transparent: true,
	      opacity: themes.light.vectorOpacity,
	      depthWrite: false,
	      depthTest: false,
	    });
	    const vectorDashCount = 96;
	    const vectorDashSets = cameraMarkers.map(() => {
	      const dashes = [];
	      const group = new THREE.Group();
	      for (let i = 0; i < vectorDashCount; i += 1) {
	        const dash = new THREE.Mesh(vectorDashGeometry, vectorMat);
	        dash.visible = false;
	        dash.frustumCulled = false;
	        dash.renderOrder = 40;
	        group.add(dash);
	        dashes.push(dash);
	      }
	      scene.add(group);
	      return dashes;
	    });
	    const vectorYAxis = new THREE.Vector3(0, 1, 0);

	    function hideVectorDashes(dashes) {
	      for (const dash of dashes) dash.visible = false;
	    }

	    function placeVectorDash(dash, start, end, thickness) {
	      const segment = new THREE.Vector3().subVectors(end, start);
	      const length = segment.length();
	      if (length <= 0.001) {
	        dash.visible = false;
	        return;
	      }
	      dash.position.copy(start).add(end).multiplyScalar(0.5);
	      dash.quaternion.setFromUnitVectors(vectorYAxis, segment.normalize());
	      dash.scale.set(thickness, length, thickness);
	      dash.visible = true;
	    }

	    function updateVectorDashes(dashes, start, end) {
	      const direction = new THREE.Vector3().subVectors(end, start);
	      const totalLength = direction.length();
	      if (totalLength <= 0.001) {
	        hideVectorDashes(dashes);
	        return;
	      }
	      direction.normalize();
	      const dashLength = Math.max(radius * 0.05, 0.55);
	      const gapLength = dashLength * 0.62;
	      const thickness = Math.max(radius * 0.009, 0.075);
	      let cursor = 0;
	      let dashIndex = 0;
	      while (cursor < totalLength && dashIndex < dashes.length) {
	        const dashStart = start.clone().addScaledVector(direction, cursor);
	        const dashEnd = start.clone().addScaledVector(direction, Math.min(cursor + dashLength, totalLength));
	        placeVectorDash(dashes[dashIndex], dashStart, dashEnd, thickness);
	        cursor += dashLength + gapLength;
	        dashIndex += 1;
	      }
	      for (; dashIndex < dashes.length; dashIndex += 1) dashes[dashIndex].visible = false;
	    }

	    const shadowTexture = makeShadowTexture();
	    const droneShadow = new THREE.Mesh(
	      new THREE.CircleGeometry(1, 72),
	      new THREE.MeshBasicMaterial({
	        map: shadowTexture,
	        color: themes.light.shadow,
	        transparent: true,
	        opacity: themes.light.shadowOpacity,
	        depthWrite: false,
	        depthTest: false,
	        side: THREE.DoubleSide,
	      }),
	    );
	    droneShadow.rotation.x = -Math.PI / 2;
	    droneShadow.position.set(center.x, groundY + Math.max(radius * 0.0015, 0.01), center.z);
	    droneShadow.renderOrder = 18;
	    scene.add(droneShadow);

		    const drone = makeSvgSprite(droneSvgIcon, droneTexture, Math.max(radius * 0.17, 1.35));
	    drone.renderOrder = 60;
	    drone.material.depthTest = false;
	    const dropGeo = new THREE.BufferGeometry();
	    const dropLine = new THREE.Line(dropGeo, new THREE.LineBasicMaterial({ color: themes.light.drop, transparent: true, opacity: 0.48 }));
	    const pointLight = new THREE.PointLight(themes.light.drone, 0.9, radius * 1.1);
	    scene.add(drone, dropLine, pointLight);

    function nearestIndex(points, relT) {
      if (!points.length) return -1;
      let lo = 0;
      let hi = points.length - 1;
      while (lo < hi) {
        const mid = Math.floor((lo + hi) / 2);
        if (points[mid].t < relT) lo = mid + 1;
        else hi = mid;
      }
      if (lo > 0 && Math.abs(points[lo - 1].t - relT) < Math.abs(points[lo].t - relT)) return lo - 1;
      return lo;
    }

    function nearestPathPoint(path, relT, recording) {
      if (!path.length) return null;
      const globalT = sceneStartEpoch + relT;
      let best = path[0];
      let bestDistance = Math.abs(recording.created_epoch + best.video_t - globalT);
      for (let i = 1; i < path.length; i += Math.max(1, Math.floor(path.length / 240))) {
        const distance = Math.abs(recording.created_epoch + path[i].video_t - globalT);
        if (distance < bestDistance) {
          best = path[i];
          bestDistance = distance;
        }
	      }
	      return best;
	    }

	    const sceneStartEpoch = Math.min(...sceneData.recordings.map((recording) => recording.created_epoch));
    const minT = smooth.length ? smooth[0].t : 0;
    const maxT = smooth.length ? smooth[smooth.length - 1].t : 1;
    const timeline = document.getElementById('timeline');
    const timeLabel = document.getElementById('time');
    const playButton = document.getElementById('play');
    const themeToggle = document.getElementById('theme-toggle');
    timeline.min = minT.toFixed(2);
    timeline.max = maxT.toFixed(2);
    timeline.step = '0.05';
    timeline.value = minT.toFixed(2);

    document.getElementById('recordings').textContent = sceneData.recordings.length;
    document.getElementById('observations').textContent = sceneData.observations;
    document.getElementById('smooth-points').textContent = smooth.length;
    document.getElementById('warning').textContent = sceneData.warning;

    let playing = true;
    let currentT = minT;
    let lastFrame = performance.now();
    let playbackSpeed = 1.6;

    playButton.addEventListener('click', () => {
      playing = !playing;
      playButton.textContent = playing ? 'Pause' : 'Play';
    });
    themeToggle.addEventListener('click', () => {
      currentTheme = currentTheme === 'light' ? 'dark' : 'light';
      applyTheme();
    });
    timeline.addEventListener('input', () => {
      currentT = Number(timeline.value);
      playing = false;
      playButton.textContent = 'Play';
      updateCurrent(currentT);
    });
    playButton.textContent = 'Pause';

    function setMaterialColor(material, color) {
      if (!material) return;
      if (Array.isArray(material)) {
        for (const item of material) setMaterialColor(item, color);
      } else if (material.color) {
        material.color.setHex(color);
      }
    }

    function applyTheme() {
      const theme = themes[currentTheme];
      document.body.dataset.theme = currentTheme;
      themeToggle.textContent = currentTheme === 'light' ? 'Dark' : 'Light';
      scene.background.setHex(theme.background);
      scene.fog.color.setHex(theme.fog);
      scene.fog.density = theme.fogDensity;
      ambient.color.setHex(theme.ambient);
      ambient.intensity = theme.ambientIntensity;
      sun.color.setHex(theme.sun);
      sun.intensity = theme.sunIntensity;
      if (Array.isArray(grid.material)) {
        setMaterialColor(grid.material[0], theme.gridMajor);
        setMaterialColor(grid.material[1], theme.gridMinor);
      } else {
        setMaterialColor(grid.material, theme.gridMinor);
      }
	      if (fullTube) {
	        fullTube.material.color.setHex(theme.fullTube);
	        fullTube.material.emissive.setHex(theme.fullTube);
	        fullTube.material.opacity = currentTheme === 'light' ? 0.28 : 0.22;
	      }
	      trailMat.color.setHex(theme.trail);
	      vectorMat.color.setHex(theme.vector);
	      vectorMat.opacity = theme.vectorOpacity;
	      droneShadow.material.color.setHex(theme.shadow);
	      droneShadow.material.opacity = theme.shadowOpacity;
	      dropLine.material.color.setHex(theme.drop);
	      pointLight.color.setHex(theme.drone);
	    }

    function updateCurrent(relT) {
      if (!smooth.length) return;
      const idx = nearestIndex(smooth, relT);
	      const current = smooth[idx];
	      const position = vectorFromPoint(current);
	      drone.position.copy(position);
	      faceCamera(drone);
	      const altitude = Math.max(0, current.y - groundY);
	      const altitudeRatio = Math.min(altitude / Math.max(radius * 0.72, 1), 1.35);
	      const shadowSize = Math.max(radius * 0.13, 1.2) + Math.max(radius * 0.28, 2.8) * altitudeRatio;
	      droneShadow.position.set(current.x, groundY + Math.max(radius * 0.0015, 0.01), current.z);
	      droneShadow.scale.set(shadowSize, shadowSize, 1);
	      pointLight.position.copy(position);
	      dropGeo.setFromPoints([position, new THREE.Vector3(current.x, groundY, current.z)]);
	      trailGeo.setDrawRange(0, idx + 1);

	      for (const [entryIndex, entry] of cameraMarkers.entries()) {
	        const point = nearestPathPoint(entry.recording.path, relT, entry.recording);
		        if (!point) {
		          hideVectorDashes(vectorDashSets[entryIndex]);
		          continue;
		        }
		        const markerPosition = vectorFromPoint(point);
		        entry.marker.position.copy(markerPosition);
		        faceCamera(entry.marker);
		        entry.label.position.copy(markerPosition.clone().add(new THREE.Vector3(radius * 0.025, radius * 0.025, 0)));
	        updateVectorDashes(vectorDashSets[entryIndex], markerPosition, position);
		      }

	      document.getElementById('coord-x').textContent = current.x.toFixed(2);
      document.getElementById('coord-y').textContent = current.y.toFixed(2);
      document.getElementById('coord-z').textContent = current.z.toFixed(2);
      document.getElementById('residual').textContent = `${current.residual.toFixed(2)} m`;
      document.getElementById('devices').textContent = current.devices.join('+') || '-';
      timeLabel.textContent = `t ${relT.toFixed(2)}s`;
      timeline.value = relT.toFixed(2);
    }

    function animate(now) {
      const dt = Math.min((now - lastFrame) / 1000, 0.08);
      lastFrame = now;
	      if (playing && smooth.length) {
	        currentT += dt * playbackSpeed;
	        if (currentT > maxT) currentT = minT;
	        updateCurrent(currentT);
	      }
	      controls.update();
	      faceCamera(drone);
	      for (const entry of cameraMarkers) faceCamera(entry.marker);
	      renderer.render(scene, camera);
      requestAnimationFrame(animate);
    }

    window.addEventListener('resize', () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    });

	    applyTheme();
	    updateCurrent(currentT);
	    controls.update();
	    renderer.render(scene, camera);
	    requestAnimationFrame(animate);
    }
  </script>
	</body>
	</html>
	"""
HTML = HTML.replace("__TOWER_SVG__", json.dumps(TOWER_SVG))
HTML = HTML.replace("__DRONE_SVG__", json.dumps(DRONE_SVG))


class SceneHandler(BaseHTTPRequestHandler):
    scene_json = "{}"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in {"/", "/index.html"}:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
            return
        if path == "/scene.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(self.scene_json.encode("utf-8"))
            return
        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        self.send_error(404)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}", file=sys.stderr)


def bind_server(host: str, port: int) -> ThreadingHTTPServer:
    last_error: OSError | None = None
    for candidate in range(port, port + 50):
        try:
            return ThreadingHTTPServer((host, candidate), SceneHandler)
        except OSError as exc:
            last_error = exc
    raise RuntimeError(f"could not bind a port starting at {port}: {last_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve a Three.js 3D viewer for Triangometry tracks.")
    parser.add_argument("--data", default="data", help="directory containing .mov + *_metadata.json files")
    parser.add_argument(
        "--rendered-dir",
        default="rendered",
        help="directory containing *_coordinates.json files; defaults to rendered/ under --data",
    )
    parser.add_argument("--fps", type=float, default=2.0, help="video analysis sample rate for fallback detector")
    parser.add_argument("--width", type=int, default=480, help="scaled video width for fallback detector")
    parser.add_argument("--bin-seconds", type=float, default=0.05, help="time bin for multi-camera matching")
    parser.add_argument("--smooth-step", type=float, default=0.05, help="output timestep for the smoothed track")
    parser.add_argument("--smooth-max-speed", type=float, default=5.0, help="maximum smoothed drone speed")
    parser.add_argument("--smooth-alpha", type=float, default=0.55, help="measurement pull strength for smoothing")
    parser.add_argument("--smooth-gap", type=float, default=0.16, help="maximum time gap for direct measurement use")
    parser.add_argument("--smooth-window", type=float, default=0.75, help="median-filter window before smoothing")
    parser.add_argument("--smooth-residual-gate", type=float, default=15.0, help="raw residual gate for smoothing")
    parser.add_argument("--smooth-max-accel", type=float, default=8.0, help="maximum smoothed acceleration")
    parser.add_argument("--no-smoothing", action="store_true", help="show and export the unsmoothed raw track")
    parser.add_argument("--force", action="store_true", help="rebuild cached fallback detections")
    parser.add_argument("--use-video-detection", action="store_true", help="fallback to slow ffmpeg detection")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port; next free port is used if busy")
    parser.add_argument("--no-open", action="store_true", help="do not open a browser automatically")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scene = build_scene(args)
    SceneHandler.scene_json = json.dumps(scene)

    server = bind_server(args.host, args.port)
    host, port = server.server_address
    url = f"http://{host}:{port}/"
    print(f"serving Triangometry 3D viewer at {url}")
    print("press Ctrl+C to stop")

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
