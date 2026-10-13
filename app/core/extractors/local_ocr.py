"""Offline extraction with Tesseract. Runs entirely on the host; nothing leaves the machine."""

from __future__ import annotations

import re
import time

import pytesseract
from PIL import Image

from ..models import ExtractedLabel
from ..preprocess import prepare_for_ocr
from ..stroke import heading_weight_ratio
from .base import ProviderUnavailableError

_ALNUM = re.compile(r"[^A-Za-z0-9]")


def _key(word: str) -> str:
    return _ALNUM.sub("", word).upper()


def tesseract_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except (pytesseract.TesseractNotFoundError, OSError):
        return False


def _run(gray, psm: int, timeout: float) -> tuple[list[list[tuple[str, float, tuple]]], float]:
    """OCR once. Returns lines of (word, confidence 0..100, box) and a 0..1 readability score."""
    data = pytesseract.image_to_data(
        gray, config=f"--oem 1 --psm {psm}", output_type=pytesseract.Output.DICT, timeout=timeout
    )
    lines: dict[tuple[int, int, int], list[tuple[str, float, tuple]]] = {}
    for i, text in enumerate(data["text"]):
        text = (text or "").strip()
        conf = float(data["conf"][i])
        if not text or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        box = (data["left"][i], data["top"][i], data["width"][i], data["height"][i])
        lines.setdefault(key, []).append((text, conf, box))
    ordered = [lines[k] for k in sorted(lines)]
    # Character-weighted mean so stray one-letter specks do not dominate.
    weights = [(len(_key(w)) or 1, c) for line in ordered for w, c, _ in line]
    total = sum(n for n, _ in weights)
    score = sum(n * c for n, c in weights) / total / 100 if total else 0.0
    return ordered, score


def find_warning(words: list[str]) -> tuple[int, int] | None:
    """Index range [start, end] of the government warning in the flattened word list."""
    keys = [_key(w) for w in words]
    start = None
    for i, k in enumerate(keys):
        if k == "GOVERNMENT" and i + 1 < len(keys) and keys[i + 1].startswith("WARNING"):
            start = i
            break
    if start is None:
        for i, k in enumerate(keys):
            if k.startswith("WARNING"):
                start = i
                break
    if start is None:
        # Heading missing: start at "(1) According to the Surgeon General".
        for i, k in enumerate(keys):
            if k == "ACCORDING" and "SURGEON" in keys[i:i + 5]:
                start = i - 1 if i > 0 and keys[i - 1] == "1" else i
                break
    if start is None:
        return None
    for j in range(start, min(len(keys), start + 80)):
        if keys[j].startswith("PROBLEM"):
            return start, j
    return start, min(len(keys), start + 45) - 1


class LocalOcrExtractor:
    name = "local_ocr"

    def __init__(self, retry_budget_s: float = 2.5, timeout_s: float = 20.0):
        self.retry_budget_s = retry_budget_s
        self.timeout_s = timeout_s

    def extract(self, image: Image.Image) -> ExtractedLabel:
        if not tesseract_available():
            raise ProviderUnavailableError("Offline OCR (Tesseract) is not installed on this server.")
        t0 = time.perf_counter()
        gray, notes = prepare_for_ocr(image)
        t1 = time.perf_counter()
        lines, score = _run(gray, psm=3, timeout=self.timeout_s)
        if score < 0.70 and time.perf_counter() - t1 < self.retry_budget_s:
            lines6, score6 = _run(gray, psm=6, timeout=self.timeout_s)
            if score6 > score:
                lines, score = lines6, score6
                notes.append("used single-block page layout")
        t2 = time.perf_counter()

        flat = [(w, c) for line in lines for w, c, _ in line]
        boxes = [b for line in lines for _, _, b in line]
        words = [w for w, _ in flat]
        span = find_warning(words)
        warning_text = " ".join(words[span[0]:span[1] + 1]) if span else None
        ratio = None
        if span and _key(words[span[0]]) == "GOVERNMENT" and span[1] - span[0] > 8:
            ratio = heading_weight_ratio(gray, boxes[span[0]:span[0] + 2], boxes[span[0] + 2:span[1] + 1])
        return ExtractedLabel(
            provider="local_ocr",
            full_text="\n".join(" ".join(w for w, _, _ in line) for line in lines),
            fields={},
            warning_text=warning_text,
            warning_heading_bold=None,  # OCR text carries no type weight
            warning_body_bold=None,
            confidence=round(score, 3),
            word_confidences=flat,
            extraction_ms=int((t2 - t1) * 1000),
            preprocess_ms=int((t1 - t0) * 1000),
            notes=notes,
            warning_weight_ratio=ratio,
        )
