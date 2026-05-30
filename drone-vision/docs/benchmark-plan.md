# Detection Quality Sweep — Benchmark Plan

## Ziel

5 sequenzielle Optimierungs-Iterationen, die **kumulativ** aufeinander aufbauen.
Jede Iteration fügt eine neue Optimierung hinzu, führt den Benchmark durch und
schreibt eine Zusammenfassung. Fokus: **Detection Quality** (Recall/Precision),
nicht nur Speed.

Die Optimierungen stammen aus dem Deep Research zu inference-only quality
improvements (siehe `docs/inference-optimizations-quality.md`).

---

## Setup

| Parameter | Wert |
|---|---|
| Video | `provided_data/.../Vibrations.mp4` (393 Frames, 1920x1080) |
| Model | `provided_data/.../Baseline_yolo11s_Modell.onnx` (YOLO11s, fixer 640x640 Input) |
| Runtime | ONNX Runtime CPU (Windows) |
| Baseline | `benchmarks/baseline/20260529-030256/baseline.csv` (~3.7 FPS, ~270ms Latenz, ~15% Detection Rate) |

## Feature-Toggles (CLI)

Jede Optimierung ist per CLI-Flag steuerbar, damit die Iterationen exakt
reproduzierbar sind:

| Flag | Default | Steuert |
|---|---|---|
| `--no-preprocess` | Preprocessing ON | CLAHE + Unsharp Mask |
| `--no-wbf` | WBF ON | Weighted Boxes Fusion (sonst NMS) |
| `--no-fp-filter` | FP Filter ON | Size + Aspect Ratio Filter |
| `--sahi` | SAHI OFF | Slicing Aided Hyper Inference |
| `--tta` | TTA OFF | Test-Time Augmentation |
| `--no-kalman` | Kalman ON | Kalman Filter Prediction |
| `--vote-window N` | 5 | Multi-Frame Voting Fenster |
| `--vote-threshold N` | 3 | Multi-Frame Voting Schwelle |

## Die 5 Iterationen

### Iteration 1: Image Enhancement
Baut auf: **Baseline** (keine Anderungen an Fusion/Tracking)

| Optimierung | Typ | Erwartung |
|---|---|---|
| CLAHE Pre-processing | Code (`preprocess.py`) | + Kontrast bei bewolktem Himmel |
| Unsharp Masking | Code (`preprocess.py`) | + Kanten-Scharfe |

**Flags:** `--no-wbf --no-fp-filter --no-kalman --vote-window 1 --vote-threshold 1`

**Erwartung:** +5-15% Recall bei niedrigem Kontrast, minimale Precision-Anderung.

---

### Iteration 2: Better Box Fusion
Baut auf: **Iter 1**

| Optimierung | Typ | Erwartung |
|---|---|---|
| Weighted Boxes Fusion (WBF) statt NMS | Code (`detection.py`) | + Precision, stabilere Boxen |
| False Positive Filter (Size + Aspect Ratio) | Code (`detection.py`) | - False Positives |

**Flags:** `--no-kalman --vote-window 1 --vote-threshold 1`

**Erwartung:** +2-5% Recall, +5-10% Precision.

---

### Iteration 3: SAHI (Slicing)
Baut auf: **Iter 1+2**

| Optimierung | Typ | Erwartung |
|---|---|---|
| SAHI: 320x320 Tiles, 20% Overlap | Code (`detection.py`, `SahiDetector`) | ++ Recall fur kleine Drohnen |

**Flags:** `--sahi --no-kalman --vote-window 1 --vote-threshold 1`

**Erwartung:** +20-50% Recall bei kleinen/entfernten Drohnen, hoher Latenz-Overhead.

---

### Iteration 4: Temporal Smoothing
Baut auf: **Iter 1+2+3**

| Optimierung | Typ | Erwartung |
|---|---|---|
| Kalman Filter Interpolation (missed frames) | Code (`tracking.py`) | - Lost Detections |
| Multi-Frame Voting (M=3 von N=5) | Code (`tracking.py`) | - Single-Frame False Positives |

**Flags:** `--sahi`

**Erwartung:** +10-20% effektive Detection Rate, -30-60% single-frame FPs.

---

### Iteration 5: Full Ensemble
Baut auf: **Iter 1+2+3+4**

| Optimierung | Typ | Erwartung |
|---|---|---|
| TTA: Multi-Scale (640+960) + Horizontal Flip | Code (`detection.py`, `TtaDetector`) | Maximale Recall |
| WBF Fusion aller Ensemble-Results | Code (`detection.py`, `_wbf_fusion`) | Beste Precision |

**Flags:** `--sahi --tta`

**Erwartung:** +10-20% zusatzlicher Recall, ~1s/Frame Latenz (4x inferenz).

---

## Ausfuhrung

Der Sweep wird via `tools/sweep.py` gestartet:

```
python tools/sweep.py --output-dir benchmarks/sweep
```

Das Skript:
1. Fuhrt `detect_drone.py` mit den Flags der jeweiligen Iteration aus
2. Speichert das CSV in `benchmarks/sweep/iter_N/detections.csv`
3. Vergleicht gegen die Baseline via `tools/benchmark.py diff`
4. Schreibt `benchmarks/sweep/iter_N/summary.md`
5. Am Ende: `benchmarks/sweep/final_summary.md` mit Vergleichstabelle

---

## Geanderte Dateien

| Datei | Aktion |
|---|---|
| `docs/inference-optimizations-quality.md` | NEU -- Deep Research zu Quality-Optimierungen |
| `drone_overlay/preprocess.py` | NEU -- CLAHE + Unsharp Mask preprocessing |
| `drone_overlay/detection.py` | Edit -- WBF statt NMS, SAHI, TTA, Preprocess-Aufruf, Feature-Toggles |
| `drone_overlay/tracking.py` | Edit -- Kalman Filter, Multi-Frame Voting |
| `drone_overlay/video.py` | Edit -- Preprocess-Call vor predict(), SAHI/TTA-Komposition |
| `drone_overlay/cli.py` | Edit -- Neue CLI-Args fur alle Features |
| `tools/sweep.py` | NEU -- 5-Iteration Quality Sweep Runner |
| `.kilo/setup-script.ps1` | NEU -- Windows Setup fur Agent Manager |
| `requirements.txt` | Edit -- onnxruntime, onnx, ensemble-boxes |

---

## Ergebnis-Tabelle (final_summary.md)

| Iteration | Avg FPS | Avg Latency | Detected Frames | Detection Rate | Avg Confidence | delta vs Baseline |
|---|---|---|---|---|---|---|
| Baseline | ~3.7 | ~270ms | ~60 | ~15% | ~0.55 | -- |
| 1: Image Enhancement | ? | ? | ? | ? | ? | +X |
| 2: +WBF +FP-Filter | ? | ? | ? | ? | ? | +X |
| 3: +SAHI | ? | ? | ? | ? | ? | +X |
| 4: +Temporal | ? | ? | ? | ? | ? | +X |
| 5: +Ensemble | ? | ? | ? | ? | ? | +X |

---

## Bekannte Einschrankungen

- **ONNX-Modell fixer Input**: Das Modell hat einen festen 640x640 Input.
  `--imgsz 960` ist damit nicht kompatibel. Der Detector auto-detektiert die
  Input-Grosse und ignoriert abweichende `--imgsz`-Werte.
- **CPU-only**: Alle Benchmarks laufen auf CPU (keine GPU/CoreML). ~250ms/Frame
  Baseline. SAHI und TTA konnen mehrere Minuten pro Iteration dauern.
- **Single-Target Tracker**: Der `SmoothedTargetTracker` verfolgt nur ein Ziel.
  Die Quality-Verbesserungen beziehen sich auf die Fahigkeit, dieses eine Ziel
  zu erkennen und zu halten.
