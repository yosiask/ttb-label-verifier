"""Measures type weight from pixels: how much heavier the warning heading is than its body.

Used as an independent check on a vision model's bold judgment. Live testing showed the model
sometimes calls a regular-weight "GOVERNMENT WARNING:" bold, which alone would let a label pass.
The measurement is relative (heading stroke / body stroke on the same image), so it does not
depend on resolution or font size, only on both parts using the same typeface at similar size.
Compliant labels need the heading bold and the body not: a heading clearly heavier than the body.
"""

from __future__ import annotations

import cv2
import numpy as np

Box = tuple[int, int, int, int]  # left, top, width, height


def stroke_width(gray: np.ndarray, box: Box) -> float | None:
    """Typical stroke thickness in pixels of the dark text inside box: twice the mean
    distance-to-background along the strokes' centre lines."""
    left, top, w, h = box
    crop = gray[max(0, top - 2):top + h + 2, max(0, left - 2):left + w + 2]
    if crop.size == 0 or w < 4 or h < 4:
        return None
    _, ink = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if (ink > 0).mean() > 0.6:  # light text on a dark background
        ink = 255 - ink
    dist = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    ridge = (dist >= cv2.dilate(dist, np.ones((3, 3), np.uint8))) & (dist > 0.5)
    return float(2 * dist[ridge].mean()) if ridge.any() else None


def heading_weight_ratio(gray: np.ndarray, heading: list[Box], body: list[Box],
                         height_ratio_range: tuple[float, float] = (0.7, 1.4)) -> float | None:
    """Heading stroke / median body stroke, or None when it cannot be measured fairly
    (missing words, or heading and body set at clearly different sizes)."""
    if not heading or len(body) < 5:
        return None
    hs = [s for s in (stroke_width(gray, b) for b in heading) if s]
    bs = [s for s in (stroke_width(gray, b) for b in body) if s]
    if not hs or len(bs) < 5:
        return None
    size = float(np.median([b[3] for b in heading])) / float(np.median([b[3] for b in body]))
    if not height_ratio_range[0] <= size <= height_ratio_range[1]:
        return None
    return round(float(np.mean(hs)) / float(np.median(bs)), 3)
