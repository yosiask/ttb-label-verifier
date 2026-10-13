"""Offline extraction with Tesseract. Runs entirely on the host; nothing leaves the machine."""

from __future__ import annotations

import re
import time

import cv2
import pytesseract
from PIL import Image

from ..models import ExtractedLabel
from ..preprocess import prepare_for_ocr_with_plain
from ..stroke import heading_weight_ratio
from .base import ProviderUnavailableError

_ALNUM = re.compile(r"[^A-Za-z0-9]")
# Words of class/type statements that readers tend to "correct" toward (the reader is blind to the
# application; these lines are simply re-read close up).
CLASS_WORDS = {"BOURBON", "WHISKEY", "WHISKY", "VODKA", "GIN", "RUM", "TEQUILA", "BRANDY", "COGNAC", "MEZCAL",
               "LIQUEUR", "WINE", "ALE", "LAGER", "BEER", "PILSNER", "STOUT", "PORTER", "CIDER", "SAKE", "SCOTCH",
               "RYE", "STRAIGHT", "BLENDED", "IPA", "MALT", "KENTUCKY", "TENNESSEE"}
MAX_CLOSEUPS = 3
CLOSEUP_LINE_PX = 80  # bring every line to about this height (small type enlarged at most 2x)
CLOSEUP_MAX_PIXELS = 2_500_000


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


def closeup_lines(plain, lines, skip: set[int], timeout: float) -> list[str]:
    """Re-read each short line holding a class/type word: a band two line-heights above and below
    (and four to each side), from
    unenhanced pixels, scaled so the line is about CLOSEUP_LINE_PX tall (small type at most 2x). On registry artwork this
    read "KENTUCKY BOUBON WHISKEY" where the full-page pass (and the cloud model) read "BOURBON".
    Bounded: at most MAX_CLOSEUPS bands, each at most CLOSEUP_MAX_PIXELS after enlarging."""
    out: list[str] = []
    seen: set[str] = set()
    for i, line in enumerate(lines):
        if len(seen) >= MAX_CLOSEUPS:
            break
        keys = [_key(w) for w, _, _ in line]
        # A class statement is a short line; descriptive paragraphs that mention "bourbon" are skipped.
        if i in skip or len(keys) > 8 or not set(keys) & CLASS_WORDS or " ".join(keys) in seen:
            continue
        seen.add(" ".join(keys))
        top = min(b[1] for *_, b in line)
        bottom = max(b[1] + b[3] for *_, b in line)
        h = max(1, bottom - top)
        left = min(b[0] for *_, b in line)
        right = max(b[0] + b[2] for *_, b in line)
        band = plain[max(0, top - 2 * h):bottom + 2 * h, max(0, left - 4 * h):right + 4 * h]
        if band.size == 0:
            continue
        scale = min(2.0, CLOSEUP_LINE_PX / h, (CLOSEUP_MAX_PIXELS / band.size) ** 0.5)
        if scale != 1.0:
            band = cv2.resize(band, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)
        try:
            text = pytesseract.image_to_string(band, config="--oem 1 --psm 6", timeout=timeout)
        except RuntimeError:  # Tesseract timeout: the close-up is optional
            break
        out += [t.strip() for t in text.splitlines() if t.strip()]
    return out


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
        gray, plain, notes = prepare_for_ocr_with_plain(image)
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
        line_of = [i for i, line in enumerate(lines) for _ in line]
        words = [w for w, _ in flat]
        span = find_warning(words)
        warning_text = " ".join(words[span[0]:span[1] + 1]) if span else None
        ratio = None
        if span and _key(words[span[0]]) == "GOVERNMENT" and span[1] - span[0] > 8:
            # Body words on the heading's own printed line: same size, focus and curvature.
            s0 = span[0]
            same_line = [boxes[j] for j in range(s0 + 2, span[1] + 1) if line_of[j] == line_of[s0]]
            ratio = heading_weight_ratio(gray, boxes[s0:s0 + 2], same_line)
        warning_lines = {line_of[j] for j in range(span[0], span[1] + 1)} if span else set()
        closeups = closeup_lines(plain, lines, warning_lines, timeout=5)
        t3 = time.perf_counter()
        return ExtractedLabel(
            provider="local_ocr",
            full_text="\n".join(" ".join(w for w, _, _ in line) for line in lines),
            fields={},
            warning_text=warning_text,
            warning_heading_bold=None,  # OCR text carries no type weight
            warning_body_bold=None,
            confidence=round(score, 3),
            word_confidences=flat,
            extraction_ms=int((t3 - t1) * 1000),
            preprocess_ms=int((t1 - t0) * 1000),
            notes=notes,
            warning_weight_ratio=ratio,
            closeup_lines=closeups,
        )
