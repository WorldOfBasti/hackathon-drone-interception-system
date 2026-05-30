"""
Streamlit MTI Pipeline Dashboard v2 — Investor Pitch
Dual-model classification, larger images, pipeline flow visualization.
Single-screen, no-scroll, clean white design.
"""

from __future__ import annotations

import base64
import time
from io import BytesIO
from pathlib import Path
from typing import Optional

import cv2
import matplotlib
import numpy as np
import streamlit as st

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

VIDEO_PATH = str(Path(__file__).resolve().parent.parent / "recordings" / "best_video.mp4")
MODEL_PATH = str(Path(__file__).resolve().parent.parent / "models" / "bird_drone_classifier_final.h5")

DISPLAY_W = 480
DISPLAY_H = 856
ROI_DISPLAY = 420
ROI_SIZE = 224

MOG2_HISTORY = 300
MOG2_VAR_THRESHOLD = 8
MIN_CONTOUR_AREA = 12
ROI_PAD = 16
WARMUP_FRAMES = 60
CLASSIFIER_EVERY_N = 5

ALARM_ENTER_FRAMES = 3
ALARM_EXIT_FRAMES = 5

COL_RATIOS = [0.02, 1.0, 0.04, 1.0, 0.04, 1.0, 0.04, 1.0, 0.02]

PIPELINE_STEPS = [
    ("①", "LIVE VIDEO"),
    ("②", "MOTION DETECTION"),
    ("③", "AI INPUT"),
    ("④", "AI ANALYSIS"),
]

# ═══════════════════════════════════════════════════════════════
# CSS
# ═══════════════════════════════════════════════════════════════

CSS = """
<style>
    .stApp { background: #F7F9FC; }
    .block-container {
        max-width: none !important;
        padding: 0.7rem 1.1rem 0.45rem 1.1rem !important;
    }
    div[data-testid="stHorizontalBlock"] {
        gap: 0.7rem;
    }
    div[data-testid="stVerticalBlock"] {
        gap: 0.35rem;
    }

    h1, h2 {
        font-family: 'Inter', 'Segoe UI', system-ui, sans-serif !important;
        font-weight: 700 !important; font-size: 2.35rem !important;
        color: #1A1A2E !important; letter-spacing: -0.02em !important;
        margin: 0 !important;
        line-height: 1.05 !important;
    }

    /* ── Pipeline Headers ── */
    .pipeline-header {
        background: #FFFFFF;
        border: 2px solid #E3EAF1;
        border-radius: 8px;
        min-height: 74px;
        padding: 16px 10px;
        text-align: center;
        box-shadow: 0 2px 8px rgba(20,40,60,0.06);
        display: flex;
        align-items: center;
        justify-content: center;
        box-sizing: border-box;
    }
    .pipeline-step-num {
        display: inline-block;
        width: 34px; height: 34px;
        background: #E3F2FD; color: #1565C0;
        border-radius: 50%;
        font-size: 1.0rem; font-weight: 800;
        line-height: 34px; text-align: center;
        margin-right: 8px; vertical-align: middle;
    }
    .pipeline-title {
        display: inline;
        font-family: 'Inter', 'Segoe UI', sans-serif;
        font-weight: 800; font-size: 1.16rem;
        color: #1A1A2E;
        vertical-align: middle;
        white-space: nowrap;
    }

    /* ── Cards ── */
    .pipeline-card {
        background: #FFFFFF;
        border: 2px solid #E3EAF1;
        border-radius: 8px;
        padding: 18px 16px;
        box-shadow: 0 3px 12px rgba(20,40,60,0.08);
        text-align: center;
        box-sizing: border-box;
    }
    .pipeline-card.presentation-fill {
        width: 100%;
        aspect-ratio: 480 / 856;
        min-height: 0;
        display: flex;
        flex-direction: column;
        justify-content: center;
        overflow: hidden;
    }
    .pipeline-card.alarm {
        border: 3px solid #EF5350;
        animation: alarmPulse 1.5s ease-in-out infinite;
    }
    @keyframes alarmPulse {
        0%, 100% { box-shadow: 0 0 8px rgba(239,83,80,0.3); }
        50%      { box-shadow: 0 0 28px rgba(239,83,80,0.7); }
    }

    /* ── Arrows ── */
    @keyframes flowColor {
        0%   { color: #B0BEC5; }
        25%  { color: #42A5F5; }
        50%  { color: #1565C0; }
        75%  { color: #42A5F5; }
        100% { color: #B0BEC5; }
    }
    .pipe-arrow {
        display: flex; align-items: center; justify-content: center;
        min-height: clamp(500px, 55vh, 620px);
        font-size: 2.0rem;
        user-select: none; color: #CFD8DC;
    }
    .pipe-arrow.active {
        animation: flowColor 2.5s ease-in-out infinite;
    }

    /* ── Panel labels ── */
    .panel-label {
        font-family: 'Inter', 'Segoe UI', sans-serif;
        font-size: 0.9rem; font-weight: 800; letter-spacing: 0.08em;
        text-transform: uppercase; color: #607D8B;
        margin-bottom: 8px;
    }

    /* ── Classifier output ── */
    .cls-label {
        font-size: 2.65rem; font-weight: 800;
        line-height: 1.0;
    }
    .cls-gauge-row {
        display: flex; align-items: center; margin: 8px 0;
        font-family: 'JetBrains Mono', 'Consolas', monospace;
        font-size: 0.98rem; color: #37474F;
    }
    .cls-gauge-label {
        flex: 0 0 68px;
        text-align: right; padding-right: 10px;
        font-size: 0.92rem;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .cls-gauge-bar-bg {
        flex: 1; height: 16px; background: #ECEFF1;
        border-radius: 8px; overflow: hidden;
    }
    .cls-gauge-bar {
        height: 100%; border-radius: 8px; transition: width 0.3s;
    }
    .cls-gauge-pct {
        flex: 0 0 74px;
        text-align: right; padding-left: 8px;
        font-weight: 800; font-size: 1.0rem;
    }
    .analytics-note {
        margin-top: 24px;
        font-size: 0.92rem;
        color: #607D8B;
        line-height: 1.5;
    }
    .timeline-block {
        width: 100%;
        box-sizing: border-box;
        margin-top: 26px;
        padding: 0 10px;
    }
    .timeline-block img {
        width: 100%;
        margin-top: 8px;
        border-radius: 8px;
        background: #F7F9FC;
    }

    /* ── Bottom bar ── */
    .bottom-bar {
        display: flex; justify-content: space-between;
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.0rem; color: #546E7A;
        padding: 6px 12px 0;
    }

    /* ── Button ── */
    .stButton > button {
        font-family: 'Inter', 'Segoe UI', sans-serif !important;
        font-weight: 600 !important; border-radius: 8px !important;
        padding: 0.75rem 1.45rem !important; font-size: 1.12rem !important;
        transition: all 0.2s !important;
        min-height: 3.1rem !important;
        background: #1565C0 !important;
        border: 2px solid #1565C0 !important;
        color: #FFFFFF !important;
        box-shadow: 0 3px 12px rgba(21,101,192,0.18) !important;
    }
    .stButton > button:hover {
        background: #0D47A1 !important;
        border-color: #0D47A1 !important;
    }
    div[data-testid="stImage"] img {
        width: 100%;
        aspect-ratio: 480 / 856;
        object-fit: cover;
        border-radius: 8px;
        border: 2px solid #E3EAF1;
        box-shadow: 0 3px 12px rgba(20,40,60,0.10);
        box-sizing: border-box;
    }
    div[data-testid="stProgress"] {
        margin-top: 0.15rem;
    }
    div[data-testid="stProgress"] > div {
        height: 0.6rem;
    }

    /* ── Hide Streamlit chrome ── */
    #MainMenu, footer, header[data-testid="stHeader"] { display: none !important; }
    div[data-testid="stToolbar"] { display: none !important; }
    section[data-testid="stSidebar"] { display: none !important; }
    div[data-testid="stDecoration"] { display: none !important; }
</style>
"""

# ═══════════════════════════════════════════════════════════════
# SESSION STATE
# ═══════════════════════════════════════════════════════════════

DEFAULTS = {
    "running": False,
    "done": False,
    "frame_idx": 0,
    "total_frames": 0,
    "consecutive_drone": 0,
    "consecutive_nodrone": 0,
    "status": "idle",
    "last_pred": (0.0, 0.0),
    "last_crop": None,
    "conf_history": [],
}


def init_state() -> None:
    for k, v in DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ═══════════════════════════════════════════════════════════════
# MODEL LOADERS (cached — load once, survive restarts)
# ═══════════════════════════════════════════════════════════════

@st.cache_resource
def load_drone_classifier():
    import tensorflow as tf
    tf.get_logger().setLevel("ERROR")
    return tf.keras.models.load_model(MODEL_PATH, compile=False)




# ═══════════════════════════════════════════════════════════════
# IMAGE PROCESSING
# ═══════════════════════════════════════════════════════════════

def preprocess_crop(patch_bgr: np.ndarray) -> np.ndarray:
    """Preprocess for custom Bird/Drone model (x/255.0 normalization)."""
    img = cv2.resize(patch_bgr, (ROI_SIZE, ROI_SIZE))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    return np.expand_dims(img.astype(np.float32) / 255.0, axis=0)


def extract_rois(fg_mask: np.ndarray, fw: int, fh: int
                 ) -> list[tuple[int, int, int, int]]:
    contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rois = []
    for cnt in contours:
        if cv2.contourArea(cnt) < MIN_CONTOUR_AREA:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        x = max(0, x - ROI_PAD)
        y = max(0, y - ROI_PAD)
        w = min(fw - x, w + 2 * ROI_PAD)
        h = min(fh - y, h + 2 * ROI_PAD)
        rois.append((x, y, w, h))
    return rois


def get_largest_roi_crop(frame: np.ndarray,
                          rois: list[tuple[int, int, int, int]]
                          ) -> Optional[np.ndarray]:
    if not rois:
        return None
    x, y, w, h = max(rois, key=lambda r: r[2] * r[3])
    return frame[y:y + h, x:x + w]


# ═══════════════════════════════════════════════════════════════
# FRAME RENDERING
# ═══════════════════════════════════════════════════════════════

def draw_source_overlay(frame: np.ndarray,
                        rois: list[tuple[int, int, int, int]],
                        status: str) -> np.ndarray:
    out = frame.copy()

    for i, (x, y, w, h) in enumerate(rois):
        color = (0, 100, 255) if status == "alarm" else (0, 200, 255)
        thickness = 4 if i == 0 else 2
        cv2.rectangle(out, (x, y), (x + w, y + h), color, thickness)

    status_colors = {
        "idle": (200, 200, 200),
        "motion": (0, 195, 255),
        "alarm": (50, 50, 230),
        "warmup": (200, 130, 0),
    }
    color = status_colors.get(status, (200, 200, 200))
    cv2.rectangle(out, (0, 0), (out.shape[1], 52), color, -1)
    labels = {
        "idle": "NO MOTION", "motion": "MOTION DETECTED",
        "alarm": "DRONE IN AIRSPACE", "warmup": "LEARNING BACKGROUND",
    }
    cv2.putText(out, labels.get(status, ""), (14, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 0.88, (255, 255, 255), 2, cv2.LINE_AA)

    return cv2.resize(out, (DISPLAY_W, DISPLAY_H))


def draw_mog2_overlay(fg_mask: np.ndarray) -> np.ndarray:
    colored = cv2.cvtColor(fg_mask, cv2.COLOR_GRAY2BGR)
    colored[fg_mask > 0] = (0, 220, 140)
    colored = cv2.resize(colored, (DISPLAY_W, DISPLAY_H))

    fg_pct = np.count_nonzero(fg_mask) / fg_mask.size * 100
    cv2.rectangle(colored, (0, 0), (DISPLAY_W, 48), (20, 36, 42), -1)
    cv2.putText(colored, f"MOTION MASK  {fg_pct:.1f}% FG", (16, 34),
                cv2.FONT_HERSHEY_SIMPLEX, 0.84, (230, 245, 240), 2, cv2.LINE_AA)
    return colored


def draw_roi_panel(crop: Optional[np.ndarray], status: str) -> np.ndarray:
    panel = np.full((DISPLAY_H, DISPLAY_W, 3), 245, dtype=np.uint8)
    inset = (DISPLAY_W - ROI_DISPLAY) // 2
    y0 = (DISPLAY_H - ROI_DISPLAY) // 2

    if crop is None or crop.size == 0:
        cv2.putText(panel, "NO MOTION", (145, DISPLAY_H // 2 + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.86, (160, 160, 160), 2, cv2.LINE_AA)
        return panel

    resized = cv2.resize(crop, (ROI_DISPLAY, ROI_DISPLAY))
    color = (50, 50, 230) if status == "alarm" else (100, 200, 140)
    panel[y0:y0 + ROI_DISPLAY, inset:inset + ROI_DISPLAY] = resized
    cv2.rectangle(panel, (inset, y0), (inset + ROI_DISPLAY - 1, y0 + ROI_DISPLAY - 1), color, 5)
    return panel


# ═══════════════════════════════════════════════════════════════
# SPARKLINE
# ═══════════════════════════════════════════════════════════════

def sparkline_png(history: list[float], current: float) -> BytesIO:
    fig, ax = plt.subplots(figsize=(4.4, 1.15), dpi=110, facecolor="#F7F9FC")
    ax.set_facecolor("#F7F9FC")

    padded = list(history) if history else [0.0]
    xs = list(range(len(padded)))

    if padded:
        ax.fill_between(xs, padded, alpha=0.14, color="#EF5350")
        ax.plot(xs, padded, color="#EF5350", linewidth=2.8, solid_capstyle="round")
        ax.scatter(len(padded) - 1, current, color="#C62828", s=38, zorder=5)

    ax.axhline(y=0.6, color="#B0BEC5", linewidth=1.2, linestyle="--")
    ax.set_ylim(-0.05, 1.08)
    ax.set_xlim(-0.5, max(29, len(padded) - 0.5))
    ax.axis("off")
    fig.tight_layout(pad=0.1)

    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                transparent=False, facecolor="#F7F9FC", edgecolor="none")
    plt.close(fig)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════
# HTML RENDERERS
# ═══════════════════════════════════════════════════════════════

def render_timeline_html(conf_history: list[float], drone_conf: float) -> str:
    spark = sparkline_png(conf_history, drone_conf)
    b64 = base64.b64encode(spark.read()).decode()
    return f"""\
<div class="timeline-block">
    <div class="panel-label" style="margin-bottom:4px;">confidence timeline</div>
    <img src="data:image/png;base64,{b64}" />
</div>"""


def render_classifier_html(drone_conf: float, status: str, conf_history: list[float]) -> str:
    label_color = "#C62828" if status == "alarm" else "#37474F"
    label_text = "DRONE" if drone_conf >= 0.5 else "SCANNING"
    bar_color = "#EF5350" if drone_conf >= 0.5 else "#42A5F5"
    card_class = "pipeline-card presentation-fill alarm" if status == "alarm" else "pipeline-card presentation-fill"

    drone_w = int(drone_conf * 100)
    timeline_html = render_timeline_html(conf_history, drone_conf)

    return f"""\
<div class="{card_class}">
    <div class="panel-label">④ AI ANALYSIS</div>

    <div class="cls-label" style="color:{label_color};margin-top:18px;">{label_text}</div>

    <div style="margin-top:28px;">
        <div class="cls-gauge-row">
            <span class="cls-gauge-label">score</span>
            <div class="cls-gauge-bar-bg">
                <div class="cls-gauge-bar" style="width:{drone_w}%;background:{bar_color};"></div>
            </div>
            <span class="cls-gauge-pct" style="color:{label_color};">{drone_conf:.1%}</span>
        </div>
    </div>

    <div class="analytics-note">
        analyzes every 5th frame<br>
        alarm threshold: 60%
    </div>
    {timeline_html}
</div>"""


# ═══════════════════════════════════════════════════════════════
# ALARM STATE MACHINE
# ═══════════════════════════════════════════════════════════════

def update_alarm_state(drone_conf: float, n_rois: int,
                       frame_idx: int, status: str) -> tuple[str, int]:
    if drone_conf >= 0.6:
        st.session_state.consecutive_drone += 1
        st.session_state.consecutive_nodrone = 0
    else:
        st.session_state.consecutive_drone = 0
        st.session_state.consecutive_nodrone += 1

    cd = st.session_state.consecutive_drone
    cn = st.session_state.consecutive_nodrone

    if cd >= ALARM_ENTER_FRAMES and frame_idx > WARMUP_FRAMES:
        new_status = "alarm"
    elif status == "alarm" and cn >= ALARM_EXIT_FRAMES:
        new_status = "idle"
    elif n_rois > 0 and frame_idx > WARMUP_FRAMES:
        new_status = "motion"
    elif frame_idx <= WARMUP_FRAMES:
        new_status = "warmup"
    else:
        new_status = "idle"

    consecutive = cd if new_status == "alarm" else 0
    return new_status, consecutive


# ═══════════════════════════════════════════════════════════════
# IDLE STATE
# ═══════════════════════════════════════════════════════════════

def _render_idle_state(placeholders: dict):
    placeholder_src = np.full((DISPLAY_H, DISPLAY_W, 3), 250, dtype=np.uint8)
    cv2.putText(placeholder_src, "Press START", (150, 500),
                cv2.FONT_HERSHEY_SIMPLEX, 1.15, (160, 160, 160), 2, cv2.LINE_AA)
    placeholders["source"].image(placeholder_src, width="stretch")

    for key in ("arrow1", "arrow2", "arrow3"):
        placeholders[key].markdown(
            '<div class="pipe-arrow idle">&#9654;</div>',
            unsafe_allow_html=True)

    placeholders["mog2"].image(placeholder_src, width="stretch")

    placeholders["roi"].image(draw_roi_panel(None, "idle"), width="stretch")

    placeholders["classifier"].html("""\
<div class="pipeline-card presentation-fill" style="opacity:0.6;">
    <div class="panel-label">④ AI ANALYSIS</div>
    <div class="cls-label" style="color:#90A4AE;margin-top:18px;">--</div>
    <div style="margin-top:24px;color:#78909C;font-size:0.98rem;">awaiting classification</div>
    <div class="analytics-note">
        analyzes every 5th frame<br>
        alarm threshold: 60%
    </div>
    """ + render_timeline_html([], 0.0) + """
</div>""")


# ═══════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════

def main():
    st.set_page_config(layout="wide", page_title="Drone Surveillance",
                       page_icon="🔴", initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()

    # ── Top Bar ──
    c_title, c_spacer, c_btn = st.columns([3, 1.5, 1])
    with c_title:
        st.markdown("## Drone Surveillance System")
    with c_btn:
        raw_label = "Restart Demo" if st.session_state.done else "Start Demo"
        if st.button(raw_label, width="stretch", type="primary"):
            for k, v in DEFAULTS.items():
                st.session_state[k] = v
            st.session_state.running = True
            st.rerun()

    st.markdown('<hr style="margin:6px 0 8px 0;border-color:#E8ECF0;">',
                unsafe_allow_html=True)

    # ── Pipeline Headers ──
    h_cols = st.columns(COL_RATIOS)
    for i, (num, title) in enumerate(PIPELINE_STEPS):
        idx = [1, 3, 5, 7][i]
        h_cols[idx].html(f"""\
<div class="pipeline-header">
    <span class="pipeline-step-num">{num}</span>
    <span class="pipeline-title">{title}</span>
</div>""")

    st.markdown('<div style="height:8px;"></div>', unsafe_allow_html=True)

    # ── Content Columns ──
    cols = st.columns(COL_RATIOS)
    placeholders = {
        "source":     cols[1].empty(),
        "arrow1":     cols[2].empty(),
        "mog2":       cols[3].empty(),
        "arrow2":     cols[4].empty(),
        "roi":        cols[5].empty(),
        "arrow3":     cols[6].empty(),
        "classifier": cols[7].empty(),
    }

    # ── Bottom Bar ──
    st.markdown('<hr style="margin:8px 0 4px 0;border-color:#E8ECF0;">',
                unsafe_allow_html=True)
    progress_bar = st.progress(0)
    bottom_text = st.empty()

    # ── Idle → Done ──
    if not st.session_state.running:
        _render_idle_state(placeholders)
        return

    # ── Running: Initialize Pipeline ──
    if not Path(VIDEO_PATH).exists():
        st.error("Demo video is not included in the public repo. Add your own video in recordings/ before starting.")
        _render_idle_state(placeholders)
        return

    cap = cv2.VideoCapture(VIDEO_PATH)
    st.session_state.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    mog2 = cv2.createBackgroundSubtractorMOG2(
        history=MOG2_HISTORY, varThreshold=MOG2_VAR_THRESHOLD,
        detectShadows=False)

    # Load model (cached — fast on restart)
    model_drone = load_drone_classifier()

    fi = st.session_state.frame_idx or 1
    total = st.session_state.total_frames
    fps_start = time.perf_counter()
    fps_counter = 0
    last_pred = (0.0, 0.0)
    last_crop: Optional[np.ndarray] = None
    status = "warmup"

    # ── Main Processing Loop ──
    for fi in range(fi, total + 1):
        ok, frame = cap.read()
        if not ok:
            break

        # --- MOG2 ---
        fg_mask = mog2.apply(frame, learningRate=-1)
        kernel = np.ones((3, 3), np.uint8)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        rois = extract_rois(fg_mask, fw, fh)
        crop = get_largest_roi_crop(frame, rois)

        # --- Classifier (every Nth frame, only after warmup) ---
        if fi > WARMUP_FRAMES and fi % CLASSIFIER_EVERY_N == 0 and rois and crop is not None:
            batch = preprocess_crop(crop)
            probs = model_drone.predict(batch, verbose=0)[0]
            drone_conf = float(probs[1])
            bird_conf = float(probs[0])
            last_pred = (drone_conf, bird_conf)

            last_crop = crop
            st.session_state.last_pred = last_pred
            st.session_state.last_crop = crop
        else:
            last_pred = st.session_state.last_pred
            last_crop = st.session_state.last_crop
            drone_conf, bird_conf = last_pred

        # --- Reset hysteresis counters when warmup ends ---
        if fi == WARMUP_FRAMES + 1:
            st.session_state.consecutive_drone = 0
            st.session_state.consecutive_nodrone = 0

        # --- Alarm State Machine ---
        status, consecutive = update_alarm_state(
            drone_conf, len(rois), fi, status)
        st.session_state.status = status

        # --- Confidence History ---
        st.session_state.conf_history.append(drone_conf)
        if len(st.session_state.conf_history) > 30:
            st.session_state.conf_history.pop(0)

        # ── Render Panels ──
        # Source
        src_img = draw_source_overlay(frame, rois, status)
        src_rgb = cv2.cvtColor(src_img, cv2.COLOR_BGR2RGB)
        placeholders["source"].image(src_rgb, width="stretch")

        # Arrows (animated when pipeline is active)
        arrow_cls = "pipe-arrow active" if status != "idle" else "pipe-arrow idle"
        for key in ("arrow1", "arrow2", "arrow3"):
            placeholders[key].markdown(
                f'<div class="{arrow_cls}">&#9654;</div>',
                unsafe_allow_html=True)

        # MOG2 Mask
        mog2_img = draw_mog2_overlay(fg_mask)
        mog2_rgb = cv2.cvtColor(mog2_img, cv2.COLOR_BGR2RGB)
        placeholders["mog2"].image(mog2_rgb, width="stretch")

        # ROI
        roi_img = draw_roi_panel(last_crop, status)
        roi_rgb = cv2.cvtColor(roi_img, cv2.COLOR_BGR2RGB)
        placeholders["roi"].image(roi_rgb, width="stretch")

        # Classifier
        cls_html = render_classifier_html(drone_conf, status, st.session_state.conf_history)
        placeholders["classifier"].html(cls_html)

        # ── Bottom Bar ──
        progress_bar.progress(fi / total)

        fps_counter += 1
        if fps_counter >= 5:
            now = time.perf_counter()
            fps = 5 / (now - fps_start) if now > fps_start else 0
            fps_start = now
            fps_counter = 0
            fps_val = fps
        else:
            elapsed_since = time.perf_counter() - fps_start
            fps_val = fps_counter / elapsed_since if elapsed_since > 0 else 0

        bottom_text.markdown(
            f'<div class="bottom-bar">'
            f'<span>Frame {fi}/{total}</span>'
            f'<span>FPS: {fps_val:.1f}</span>'
            f'<span>ROIs: {len(rois)}</span>'
            f'<span>Status: {status.upper()}</span>'
            f'</div>',
            unsafe_allow_html=True)

        st.session_state.frame_idx = fi

    # ── Done ──
    cap.release()
    st.session_state.running = False
    st.session_state.done = True


if __name__ == "__main__":
    main()
