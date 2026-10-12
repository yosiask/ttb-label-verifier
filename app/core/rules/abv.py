"""Alcohol content: parse ABV and proof, compare numerically.

A number counts only when it sits next to "%", "Alc", "Vol", "ABV" or "Proof".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..config import THRESHOLDS, Thresholds
from ..models import FieldCheck, Status
from ..normalize import clean

# Numbers must stand alone: "4S" (an OCR misread of 45) must not parse as 4.
_NUM = r"(?<![\w.,])(\d{1,3}(?:[.,]\d{1,2})?)(?![\w])"
_PCT = re.compile(_NUM + r"\s*%")
_ALC_BEFORE = re.compile(r"\b(?:alc(?:ohol)?|abv)\b\.?\s*(?:/\s*vol\.?)?\s*[:\-]?\s*" + _NUM, re.IGNORECASE)
_ALC_AFTER = re.compile(_NUM + r"\s*(?:alc\b|abv\b|by\s+vol)", re.IGNORECASE)
_PROOF = re.compile(_NUM + r"\s*°?\s*proof\b", re.IGNORECASE)
_KEYWORD = re.compile(r"%|\balc\b|\balcohol\b|\bvol\b|\babv\b|\bproof\b", re.IGNORECASE)

RULE = "numeric ABV match; proof must equal 2 x ABV"


def _num(s: str) -> float:
    return float(s.replace(",", "."))


@dataclass
class AlcoholReading:
    abv: list[float] = field(default_factory=list)
    proof: list[float] = field(default_factory=list)
    snippets: list[str] = field(default_factory=list)


def parse_alcohol(text: str) -> AlcoholReading:
    r = AlcoholReading()
    for line in text.splitlines():
        line = clean(line)
        seen_spans: list[tuple[int, int]] = []
        for rx in (_PCT, _ALC_BEFORE, _ALC_AFTER):
            for m in rx.finditer(line):
                if any(a <= m.start(1) < b for a, b in seen_spans):
                    continue
                v = _num(m.group(1))
                if 0 < v <= 100:
                    r.abv.append(v)
                    seen_spans.append((m.start(1), m.end(1)))
                    r.snippets.append(line)
        for m in _PROOF.finditer(line):
            v = _num(m.group(1))
            if 0 < v <= 200:
                r.proof.append(v)
                if line not in r.snippets:
                    r.snippets.append(line)
    return r


def _fmt(v: float) -> str:
    return f"{v:g}"


def check_alcohol(
    expected_raw: str,
    label_text: str,
    beverage_type: str,
    low_confidence: bool,
    extracted_value: str | None = None,
    t: Thresholds = THRESHOLDS,
) -> FieldCheck:
    def fc(status: Status, found: str | None, reason: str, **details) -> FieldCheck:
        return FieldCheck(field="alcohol_content", status=status, expected=expected_raw, found=found,
                          rule=RULE, reason=reason, details=details)

    exp = parse_alcohol(expected_raw)
    if not exp.abv and not exp.proof:
        return fc(Status.NEEDS_REVIEW, None,
                  "Could not understand the alcohol content entered in the form (expected something like \"45%\").")
    exp_abv = exp.abv[0] if exp.abv else exp.proof[0] / 2

    source = extracted_value if extracted_value is not None else label_text
    lab = parse_alcohol(source)
    found = "; ".join(dict.fromkeys(lab.snippets)) or None
    details = {"label_abv": lab.abv, "label_proof": lab.proof, "expected_abv": exp_abv}

    if not lab.abv and not lab.proof:
        if beverage_type in ("wine", "beer"):
            return fc(Status.NEEDS_REVIEW, None,
                      f"No alcohol content found. For {beverage_type}, this may be allowed in some cases; check by eye.",
                      **details)
        if low_confidence or _KEYWORD.search(source or ""):
            return fc(Status.NEEDS_REVIEW, found,
                      "Could not read the alcohol content clearly. Check by eye.", **details)
        return fc(Status.FAIL, None, "No alcohol content statement was found on the label.", **details)

    # Proof on the label must agree with ABV on the label.
    if lab.proof and lab.abv:
        consistent = any(abs(p - 2 * a) <= t.proof_tolerance for p in lab.proof for a in lab.abv)
        if not consistent:
            return fc(Status.FAIL, found,
                      f"The label's proof ({_fmt(lab.proof[0])}) is not twice its ABV ({_fmt(lab.abv[0])}%).", **details)

    label_abvs = lab.abv or [p / 2 for p in lab.proof]
    if not any(abs(a - exp_abv) <= t.abv_tolerance for a in label_abvs):
        shown = f"{_fmt(lab.abv[0])}%" if lab.abv else f"{_fmt(lab.proof[0])} proof"
        return fc(Status.FAIL, found,
                  f"The label shows {shown}; the application says {_fmt(exp_abv)}%.", **details)

    if exp.proof and lab.proof and not any(abs(p - exp.proof[0]) <= t.proof_tolerance for p in lab.proof):
        return fc(Status.FAIL, found,
                  f"The label shows {_fmt(lab.proof[0])} proof; the application says {_fmt(exp.proof[0])} proof.",
                  **details)

    return fc(Status.PASS, found, f"Alcohol content matches ({_fmt(exp_abv)}%).", **details)
