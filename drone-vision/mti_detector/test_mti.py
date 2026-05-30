"""Component-level tests for the MOG2 -> YOLO MTI pipeline.

Tests each module in isolation with synthetic data.
No video files, no drone, no YOLO model needed for Level 1+2.

Usage:
    python -m mti_detector.test_mti --level 1    # Pure Python, no deps
    python -m mti_detector.test_mti --level 2    # +MOG2+morph (needs cv2)
    python -m mti_detector.test_mti --level 3    # +Full pipeline (needs onnx)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PASS = "  PASS"
FAIL = "  FAIL"
SKIP = "  SKIP"


def check_cv2() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


def check_onnx() -> bool:
    try:
        import onnxruntime  # noqa: F401
        return True
    except ImportError:
        return False


# ── Level 1: Pure Python ──────────────────────────────────────────

def test_mti_result_dataclass() -> bool:
    from mti_detector.mti_guided_detector import MtiResult
    r = MtiResult(frame_count=42, detection_source="mti", processing_ms=12.5)
    assert r.fg_mask is None
    assert r.rois == []
    assert r.detections == []
    assert r.frame_count == 42
    print(PASS, "MtiResult dataclass fields + defaults")
    return True


def test_bg_subtractor_init() -> bool:
    try:
        from mti_detector.bg_subtraction import BackgroundSubtractor
    except ImportError:
        print(SKIP, "BackgroundSubtractor (no cv2)")
        return True
    bg = BackgroundSubtractor(history=300, var_threshold=14, learning_rate=0.002)
    assert bg.var_threshold == 14
    assert bg.frame_count == 0
    bg.var_threshold = 18
    assert bg.var_threshold == 18
    print(PASS, "BackgroundSubtractor init + setter")
    return True


# ── Level 2: cv2-dependent ────────────────────────────────────────

def test_mog2_detects_moving_dot() -> bool:
    """Synthetic sky + moving black dot -> MOG2 must produce foreground."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        print(SKIP, "MOG2 synthetic (no cv2)")
        return True

    from mti_detector.bg_subtraction import BackgroundSubtractor

    frames = []
    for i in range(300):
        sky = np.full((480, 640, 3), (135, 206, 235), dtype=np.uint8)
        x, y = 100 + i, 200 + int(30 * np.sin(i * 0.1))
        cv2.circle(sky, (x, y), 6, (0, 0, 0), -1)
        frames.append(sky)

    bg = BackgroundSubtractor(history=100, var_threshold=16, learning_rate=-1)
    warmup = 80
    for i in range(warmup):
        bg.apply(frames[i])

    fg_hits, total_px = 0, 0
    for i in range(warmup, len(frames)):
        fg = bg.apply(frames[i])
        px = int((fg > 0).sum())
        total_px += px
        if px > 0:
            fg_hits += 1

    test_n = len(frames) - warmup
    print(f"    Warmup={warmup} Test={test_n}  FG frames={fg_hits}  "
          f"Avg px={total_px / max(test_n, 1):.1f}")
    success = fg_hits > test_n * 0.5
    print(PASS if success else FAIL, "MOG2 detects moving dot")
    return success


def test_morph_order_close_first() -> bool:
    """CLOSE-first produces fewer contours (cleaner) than OPEN-first."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        print(SKIP, "Morph order (no cv2)")
        return True

    mask = np.zeros((200, 200), dtype=np.uint8)
    mask[70:130, 70:130] = 255
    mask[75:125, 75:125] = 0
    mask[80:120, 80:120] = 255
    mask[15, 15] = 255
    mask[180, 20] = 255
    mask[25, 175] = 255

    ck = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    ok = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    cf = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, ck)
    cf = cv2.morphologyEx(cf, cv2.MORPH_OPEN, ok)

    of_ = cv2.morphologyEx(mask, cv2.MORPH_OPEN, ck)
    of_ = cv2.morphologyEx(of_, cv2.MORPH_CLOSE, ok)

    cf_n = len(cv2.findContours(cf, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0])
    of_n = len(cv2.findContours(of_, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0])
    print(f"    CLOSE->OPEN: {cf_n} contours  OPEN->CLOSE: {of_n} contours")
    print(PASS if cf_n <= of_n else FAIL, "CLOSE-first is cleaner")
    return cf_n <= of_n


def test_contour_area_filtering() -> bool:
    """Sub-min_area contours are discarded."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        print(SKIP, "Contour filter (no cv2)")
        return True

    mask = np.zeros((300, 400), dtype=np.uint8)
    cv2.circle(mask, (200, 150), 12, 255, -1)
    cv2.rectangle(mask, (5, 5), (8, 8), 255, -1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_area = 40
    kept = [c for c in contours if cv2.contourArea(c) >= min_area]
    print(f"    {len(contours)} raw -> {len(kept)} after min_area={min_area}")
    print(PASS if len(kept) == 1 else FAIL, "Area filter keeps only large contour")
    return len(kept) == 1


def test_bgsubtractor_reset() -> bool:
    try:
        import cv2
        import numpy as np
        from mti_detector.bg_subtraction import BackgroundSubtractor
    except ImportError:
        print(SKIP, "Reset (no cv2)")
        return True

    bg = BackgroundSubtractor()
    for _ in range(25):
        bg.apply(np.zeros((100, 100, 3), dtype=np.uint8))
    assert bg.frame_count == 25
    bg.reset()
    assert bg.frame_count == 0
    print(PASS, "Reset zeros counter (was 25 -> 0)")
    return True


# ── Level 3: Full pipeline (needs onnx + model) ───────────────────

def _find_model() -> str | None:
    for p in [
        "provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx",
        "drone-vision/provided_data/drive-download-20260528T184848Z-3-001/Baseline_yolo11s_Modell.onnx",
    ]:
        if Path(p).exists():
            return str(p)
    return None


def test_warmup_uses_full_frame() -> bool:
    try:
        import cv2
        import numpy as np
    except ImportError:
        print(SKIP + " (L3)", "Warmup")
        return True
    if not check_onnx():
        print(SKIP + " (no onnx)", "Warmup")
        return True
    model = _find_model()
    if not model:
        print(SKIP + " (no model)", "Warmup")
        return True

    from mti_detector.mti_guided_detector import MtiGuidedDetector
    det = MtiGuidedDetector(model, warmup_frames=3, onnx_provider="cpu")
    frame = np.full((320, 320, 3), (100, 150, 200), dtype=np.uint8)
    sources = [det.process_frame(frame, confidence=0.99).detection_source for _ in range(5)]
    print(f"    Sources: {sources}")
    print(PASS if sources[:3] == ["warmup"] * 3 else FAIL, "First 3 frames = warmup")
    return sources[:3] == ["warmup"] * 3


def test_static_triggers_fallback() -> bool:
    try:
        import cv2
        import numpy as np
    except ImportError:
        print(SKIP + " (L3)", "Fallback")
        return True
    if not check_onnx():
        print(SKIP + " (no onnx)", "Fallback")
        return True
    model = _find_model()
    if not model:
        print(SKIP + " (no model)", "Fallback")
        return True

    from mti_detector.mti_guided_detector import MtiGuidedDetector
    det = MtiGuidedDetector(model, warmup_frames=2, onnx_provider="cpu")
    static = np.full((320, 320, 3), (100, 150, 200), dtype=np.uint8)
    for _ in range(2):
        det.process_frame(static, confidence=0.99)
    r = det.process_frame(static, confidence=0.99)
    print(f"    Source={r.detection_source} ROIs={len(r.rois)}")
    print(PASS if r.detection_source == "full_frame_fallback" else FAIL, "Static -> fallback")
    return r.detection_source == "full_frame_fallback"


# ── Runner ─────────────────────────────────────────────────────────

def run_tests(level: int) -> int:
    failures, total = 0, 0

    def run(name, fn, min_lev=1):
        nonlocal failures, total
        if level < min_lev:
            return
        total += 1
        print(f"\n[{name}]")
        try:
            if not fn():
                failures += 1
        except Exception as e:
            print(FAIL, f"{type(e).__name__}: {e}")
            failures += 1

    deps = []
    if not check_cv2():
        deps.append("opencv-python")
    if level >= 3 and not check_onnx():
        deps.append("onnxruntime")
    if deps:
        print(f"WARNING: missing {' '.join(deps)}. pip install {' '.join(deps)}")

    print("=" * 60)
    print(f"MTI Pipeline Tests — Level {level}")
    print("=" * 60)

    run("MtiResult dataclass", test_mti_result_dataclass, 1)
    run("BackgroundSubtractor init", test_bg_subtractor_init, 1)
    run("MOG2 detects moving dot", test_mog2_detects_moving_dot, 2)
    run("CLOSE-first morph order", test_morph_order_close_first, 2)
    run("Contour area filtering", test_contour_area_filtering, 2)
    run("BGSubtractor reset", test_bgsubtractor_reset, 2)
    run("Warmup full-frame source", test_warmup_uses_full_frame, 3)
    run("Static triggers fallback", test_static_triggers_fallback, 3)

    print("\n" + "=" * 60)
    if failures == 0:
        print(f"ALL {total} TESTS PASSED")
    else:
        print(f"{failures}/{total} FAILED")
    print("=" * 60)
    return failures


def main(argv=None):
    p = argparse.ArgumentParser(description="Test MOG2->YOLO components")
    p.add_argument("--level", type=int, default=2, choices=[1, 2, 3])
    args = p.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    return run_tests(args.level)


if __name__ == "__main__":
    raise SystemExit(main())
