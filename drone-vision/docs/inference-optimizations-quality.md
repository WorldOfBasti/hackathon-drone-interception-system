# Inference-Only Quality Optimizations for Drone Detection

Deep Research: Techniques to improve detection recall and precision without retraining the model.

---

## 1. Image Enhancement (Preprocessing)

### CLAHE (Contrast Limited Adaptive Histogram Equalization)
- **What**: Local histogram equalization on LAB color space L-channel, limited by clip limit to avoid noise amplification.
- **Why for drones**: Small drones against bright/cloudy sky have low local contrast. CLAHE enhances edge visibility in regions where the drone blends into background.
- **Implementation**: `cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))` on L-channel of LAB colorspace.
- **Expected gain**: +5-15% recall on low-contrast frames, negligible precision impact.

### Unsharp Masking
- **What**: Gaussian blur subtraction added back to original image (sharpening filter).
- **Why**: Enhances high-frequency edges (drone silhouette against sky), making YOLO feature extraction more effective.
- **Implementation**: `cv2.addWeighted(original, 1.5, cv2.GaussianBlur(original, (0,0), 3.0), -0.5, 0)`.
- **Expected gain**: +3-8% recall on distant/small drones, minor speed cost (~2-5ms/frame).

### Increased Input Resolution
- **What**: Higher `--imgsz` (e.g., 960 instead of 640).
- **Why**: Small drones occupy few pixels at 640×640. Larger input preserves more spatial detail.
- **Trade-off**: ~2.25× more pixels means ~2-4× slower CPU inference.
- **Expected gain**: Significant recall improvement for distant drones (10-30%).

---

## 2. Better Box Fusion

### Weighted Boxes Fusion (WBF) vs NMS
- **NMS (Non-Maximum Suppression)**: Keeps only the highest-confidence box; discards all overlapping boxes. Can discard correct boxes that partially overlap.
- **WBF**: Computes weighted average of all overlapping boxes (weighted by confidence). Produces more stable, accurate box positions.
- **Implementation**: `ensemble-boxes` library. Boxes normalized to [0,1], WBF with iou_thr=0.55.
- **Expected gain**: +5-10% precision (more stable boxes), slight recall improvement from keeping merged boxes that NMS would discard.

### False Positive Filter (Size + Aspect Ratio)
- **What**: Post-fusion filter that rejects boxes with implausible dimensions.
- **Size filter**: Reject boxes smaller than N pixels (e.g., 10px) — likely noise.
- **Aspect ratio filter**: Reject boxes with aspect ratio > N:1 (e.g., 5:1) — drones are roughly square, not long/thin.
- **Expected gain**: -20-50% false positives, minimal recall impact.

---

## 3. SAHI (Slicing Aided Hyper Inference)

- **What**: Divide frame into overlapping tiles, run inference on each tile, merge results.
- **Why**: Small objects far away are "invisible" after downsampling to model input size. SAHI processes them at higher effective resolution.
- **Parameters**: 320×320 tiles with 20% overlap (64px stride = 256px).
- **Trade-off**: N tiles × inference time. For 1920×1080 frame: ~35 tiles at 320×320 with 20% overlap.
- **Merge**: WBF across all tiles for final detections.
- **Expected gain**: +20-50% recall for small/distant drones, significant latency cost.

---

## 4. Temporal Smoothing

### Kalman Filter Interpolation
- **What**: Constant-velocity Kalman filter to predict target position during missed detection frames.
- **Why**: YOLO occasionally misses detections (partial occlusion, motion blur, low contrast). Kalman bridges these gaps.
- **Implementation**: 4-state Kalman (x, y, vx, vy). Predict during missed frames, correct when detection returns.
- **Expected gain**: +10-20% effective detection rate (fewer lost targets).

### Multi-Frame Voting (M-of-N Confirmation)
- **What**: Only confirm a detection if it appears in at least M of the last N frames.
- **Why**: Single-frame false positives (background artifacts, birds, clouds) are rejected by temporal consistency check.
- **Implementation**: Ring buffer of last N detection results. Require M hits (e.g., 3 of 5) to confirm.
- **Expected gain**: -30-60% single-frame false positives, minor recall delay.

---

## 5. Test-Time Augmentation (TTA)

- **What**: Run inference multiple times with different augmentations, merge results.
- **Augmentations**:
  - Multi-scale: 640×640 and 960×960 input sizes
  - Horizontal flip
- **Why**: Different scales capture different feature representations. Flip doubles the chance of detecting asymmetric drone poses.
- **Merge**: WBF across all TTA results (4× inference per frame).
- **Trade-off**: 4× inference time. For CPU (~250ms/base) → ~1s/frame.
- **Expected gain**: +10-20% recall, best possible detection quality at inference time.

---

## Comparison Table

| Technique | Recall Gain | Precision Gain | Speed Cost | Implementation Complexity |
|---|---|---|---|---|
| CLAHE | +5-15% | ±0% | ~2-5ms | Low |
| Unsharp Mask | +3-8% | ±0% | ~2-5ms | Low |
| Resolution 640→960 | +10-30% | ±0% | ~2-4× | None (CLI flag) |
| WBF (vs NMS) | +2-5% | +5-10% | ~1-3ms | Medium |
| FP Filter | ±0% | +10-25% | ~0.1ms | Low |
| SAHI (320 tiles) | +20-50% | +0-5% | ~N× | High |
| Kalman | +10-20% | ±0% | ~0.1ms | Medium |
| Multi-Frame Vote | -1-2% | +20-40% | ~0.1ms | Medium |
| TTA (4×) | +10-20% | +0-5% | ~4× | Medium |

---

## References

- CLAHE: Zuiderveld, K. (1994). "Contrast Limited Adaptive Histogram Equalization." Graphics Gems IV.
- WBF: Solovyev, R. et al. (2021). "Weighted Boxes Fusion: Ensembling boxes for object detection models." Image and Vision Computing.
- SAHI: Akyon, F.C. et al. (2022). "Slicing Aided Hyper Inference and Fine-tuning for Small Object Detection." IEEE ICIP.
- TTA: Standard practice in object detection competitions (COCO, PASCAL VOC).
- Kalman: Kalman, R.E. (1960). "A New Approach to Linear Filtering and Prediction Problems."
