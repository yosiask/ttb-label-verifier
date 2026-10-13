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
BLUR_BELOW = 0.15  # see sharpness(): clean fixtures ~1.8-2.0, simulated photos 0.2-1.3, blurred fixture 0.10
SHARP_TILE = 40
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
    sharpness = _sharpness(gray)

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


def _sharpness(gray: np.ndarray) -> float:
    """Edge sharpness where there is detail. Each 40 px tile with visible structure (text,
    edges) scores Laplacian variance / its own gray variance, so dim or low-contrast but
    sharp text is not called blurry; the 90th percentile (the sharpest detail) is reported. Measuring only those
    tiles keeps a photo's large smooth areas (bottle, background) from looking like blur."""
    g = gray.astype(np.float64)
    lap = cv2.Laplacian(g, cv2.CV_64F)
    tiles = [(y, x, g[y:y + SHARP_TILE, x:x + SHARP_TILE].std())
             for y in range(0, g.shape[0] - SHARP_TILE + 1, SHARP_TILE)
             for x in range(0, g.shape[1] - SHARP_TILE + 1, SHARP_TILE)]
    if not tiles:
        return 0.0
    # "Visible structure" is relative to the image's most detailed tiles, so a dim photo
    # (low contrast everywhere) is judged on its own text, not on a fixed contrast level.
    floor = max(4.0, 0.4 * float(np.percentile([sd for _, _, sd in tiles], 95)))
    vals = [lap[y:y + SHARP_TILE, x:x + SHARP_TILE].var() / sd ** 2 for y, x, sd in tiles if sd >= floor]
    return float(np.percentile(vals, 90)) if vals else 0.0


def too_small_to_read(q: ImageQuality) -> bool:
    return max(q.width, q.height) < UNUSABLE_LONG_EDGE
