"""Image enhancement preprocessing for drone detection quality improvement.

Provides CLAHE contrast enhancement and Unsharp Mask sharpening, designed for
improving detection recall on small drones against sky backgrounds.
"""

from __future__ import annotations


def enhance_frame(bgr_frame):
    """Apply CLAHE + Unsharp Mask to a BGR frame.

    Returns an enhanced BGR frame of the same dimensions.
    Import-heavy (OpenCV, numpy) but callable without them at module scope.
    """
    import cv2

    lab = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_eq = clahe.apply(l_channel)
    lab_eq = cv2.merge([l_eq, a_channel, b_channel])
    enhanced = cv2.cvtColor(lab_eq, cv2.COLOR_LAB2BGR)

    blurred = cv2.GaussianBlur(enhanced, (0, 0), 3.0)
    enhanced = cv2.addWeighted(enhanced, 1.5, blurred, -0.5, 0)

    return enhanced
