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
                         target_height: int = 48) -> float | None:
    """Heading stroke / median body stroke, or None when it cannot be measured fairly.

    heading and body should be words from the same printed line (same size, focus and
    curvature). All are measured within one vertical band, the line's, because OCR word
    boxes can disagree about height, and small text is enlarged to a standard line height
    first so the strokes span enough pixels to measure.
    """
    if not heading or len(body) < 3:
        return None
    top = min(b[1] for b in heading + body)
    bottom = max(b[1] + b[3] for b in heading + body)
    line_h = bottom - top
    if line_h < 6:
        return None
    scale = min(4.0, max(1.0, target_height / line_h))

    def measure(box: Box) -> float | None:
        left, _, w, _ = box
        y0, y1 = max(0, top - 2), bottom + 2
        crop = gray[y0:y1, max(0, left - 2):left + w + 2]
        if crop.size == 0:
            return None
        if scale > 1:
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        sw = stroke_width(crop, (0, 0, crop.shape[1], crop.shape[0]))
        return sw / scale if sw else None

    left = min(b[0] for b in heading)
    right = max(b[0] + b[2] for b in heading)
    hs = measure((left, top, right - left, line_h))
    bs = [s for s in (measure(b) for b in body) if s]
    if not hs or len(bs) < 3:
        return None
    return round(hs / float(np.median(bs)), 3)
