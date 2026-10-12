"""Plain-English image quality notes (blur, darkness, contrast, resolution).

Quality notes never change a result on their own; low readability is handled by the
reader's confidence. They tell the reviewer why a result may be Needs review and what
kind of photo would help.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from .models import ImageQuality

ANALYSIS_LONG_EDGE = 1000
MIN_LONG_EDGE = 600  # below this, small print (the warning) is unlikely to be legible
UNUSABLE_LONG_EDGE = 300  # below this, nothing on a label can be read reliably
BLUR_BELOW = 0.15  # Laplacian variance / gray variance; clear fixtures ~1.1, blurred ~0.05
DARK_BELOW = 70.0
LOW_CONTRAST_BELOW = 25.0


def assess_quality(image: Image.Image) -> ImageQuality:
    w, h = image.size
    gray = np.asarray(image.convert("L"))
    s = ANALYSIS_LONG_EDGE / max(w, h)
    gray = cv2.resize(gray, (max(1, round(w * s)), max(1, round(h * s))),
                      interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    # Normalized by contrast, so a dim but sharp photo is not mistaken for a blurry one.
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var()) / max(contrast ** 2, 1.0)

    issues = []
    if max(w, h) < MIN_LONG_EDGE:
        issues.append(f"The image is small ({w} x {h} pixels); a larger photo will read more reliably.")
    if sharpness < BLUR_BELOW and max(w, h) >= MIN_LONG_EDGE:
        issues.append("The photo looks blurry.")
    if brightness < DARK_BELOW:
        issues.append("The photo is dark.")
    if contrast < LOW_CONTRAST_BELOW:
        issues.append("The photo has low contrast.")
    return ImageQuality(width=w, height=h, sharpness=round(sharpness, 3), brightness=round(brightness, 1),
                        contrast=round(contrast, 1), issues=issues)


def too_small_to_read(q: ImageQuality) -> bool:
    return max(q.width, q.height) < UNUSABLE_LONG_EDGE
