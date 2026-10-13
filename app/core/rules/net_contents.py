"""Net contents: parse a volume next to its unit, convert to mL, compare."""

from __future__ import annotations

import re

from ..config import THRESHOLDS, Thresholds
from ..models import FieldCheck, Status
from ..normalize import clean

ML_PER_UNIT = {"ml": 1.0, "cl": 10.0, "l": 1000.0, "floz": 29.5735}

_VOLUME = re.compile(
    r"(?<![\w.,])(\d+(?:[.,]\d+)*)\s*"
    r"(ml|milli-?lit(?:er|re)s?|cl|centi-?lit(?:er|re)s?|lit(?:er|re)s?|l|"
    r"(?:us\s+)?fl\.?\s*oz\.?|fluid\s+ounces?)(?![a-z])",
    re.IGNORECASE,
)
_KEYWORD = re.compile(r"\bml\b|\bcl\b|\blit(?:er|re)|\bfl\.?\s*oz|\bfluid ounce", re.IGNORECASE)
# A short line ending in a volume unit whose number was misread ("1 L" read as "TL",
# "12 FL. OZ." as "ae. OZ."): a statement is probably there, just not readable.
_UNIT_FRAGMENT = re.compile(r"^\W*[\w.]{0,4}\W*(?:m?l|cl|oz|fl\.?\s*oz)\.?\W*$", re.IGNORECASE)

RULE = "volume converted to mL, within 0.5%"


def _number(s: str) -> float:
    # "1,000" -> 1000 ; "1,75" -> 1.75 ; "1.75" -> 1.75
    if "," in s and "." not in s:
        head, _, tail = s.rpartition(",")
        s = head.replace(",", "") + ("" if len(tail) == 3 else ".") + tail
    return float(s.replace(",", ""))


def _unit(u: str) -> str:
    u = u.lower().replace(" ", "").replace(".", "")
    if u.startswith("ml") or u.startswith("milli"):
        return "ml"
    if u.startswith("cl") or u.startswith("centi"):
        return "cl"
    if "oz" in u or "fluid" in u:
        return "floz"
    return "l"


def parse_volumes(text: str) -> list[tuple[float, str]]:
    """All (mL, matched text) pairs in the text."""
    out = []
    for line in text.splitlines() or [text]:
        line = clean(line)
        for m in _VOLUME.finditer(line):
            try:
                ml = _number(m.group(1)) * ML_PER_UNIT[_unit(m.group(2))]
            except ValueError:
                continue
            if ml > 0:
                out.append((ml, line))
    return out


def _fmt_ml(ml: float) -> str:
    return f"{ml:,.1f}".rstrip("0").rstrip(".") + " mL"


def check_net_contents(
    expected_raw: str,
    label_text: str,
    low_confidence: bool,
    extracted_value: str | None = None,
    t: Thresholds = THRESHOLDS,
) -> FieldCheck:
    def fc(status: Status, found: str | None, reason: str, **details) -> FieldCheck:
        return FieldCheck(field="net_contents", status=status, expected=expected_raw, found=found,
                          rule=RULE, reason=reason, details=details)

    exp = parse_volumes(expected_raw)
    if not exp:
        return fc(Status.NEEDS_REVIEW, None,
                  "Could not understand the net contents entered in the form (expected something like \"750 mL\").")
    exp_ml = exp[0][0]
    source = extracted_value if extracted_value is not None else label_text
    found_vols = parse_volumes(source)
    details = {"expected_ml": round(exp_ml, 2), "label_ml": [round(v, 2) for v, _ in found_vols]}

    if not found_vols:
        fragment = any(_UNIT_FRAGMENT.match(line.strip()) for line in (source or "").splitlines() if line.strip())
        if low_confidence or fragment or _KEYWORD.search(source or ""):
            return fc(Status.NEEDS_REVIEW, None, "Could not read the net contents clearly. Check by eye.", **details)
        return fc(Status.FAIL, None, "No net contents statement was found on the label.", **details)

    for ml, line in found_vols:
        if abs(ml - exp_ml) <= exp_ml * t.net_contents_tolerance:
            same_unit = _fmt_ml(ml) == _fmt_ml(exp_ml) and clean(expected_raw).lower() in line.lower()
            reason = "Net contents match." if same_unit else f"Net contents match ({line} = {_fmt_ml(exp_ml)})."
            return fc(Status.PASS, line, reason, **details)
    ml, line = found_vols[0]
    return fc(Status.FAIL, line,
              f"The label shows {_fmt_ml(ml)}; the application says {_fmt_ml(exp_ml)}.", **details)
