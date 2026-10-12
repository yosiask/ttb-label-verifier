"""Brand name, class/type, producer name/address and country of origin.

Expected-guided search with a guard against false passes: finding the expected
words somewhere on the label is not the same as confirming they are that field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from ..config import THRESHOLDS, Thresholds
from ..label_text import LabelText, Span
from ..models import FieldCheck, Status
from ..normalize import clean, normalize

FIELD_LABELS = {
    "brand_name": "brand name",
    "class_type": "class/type",
    "producer_name_address": "producer name and address",
    "country_of_origin": "country of origin",
}

_PRODUCER_PREFIX = re.compile(
    r"^(?:(?:distilled|bottled|produced|blended|made|brewed|vinted|cellared|imported|"
    r"manufactured|packed|aged|crafted|and|&)\s+)+by\s+",
)
_COUNTRY_PREFIX = re.compile(
    r"\b(?:product of|produce of|produced in|imported from|made in|distilled in|country of origin)\s+(.+)$"
)
_COUNTRY_ALIASES = {
    "usa": "united states", "us": "united states", "u s a": "united states", "u s": "united states",
    "united states of america": "united states", "america": "united states",
    "uk": "united kingdom", "great britain": "united kingdom", "britain": "united kingdom",
    "holland": "netherlands", "the netherlands": "netherlands",
}


@dataclass
class TextMatch:
    check: FieldCheck
    span: Span | None
    coverage: float


def _token_recall(expected: str, span: str) -> float:
    """Share of the expected words (by length) present in the span, allowing small misreads."""
    exp_tokens = expected.split()
    span_tokens = span.split()
    if not exp_tokens or not span_tokens:
        return 0.0
    total = sum(len(t) for t in exp_tokens)
    hit = 0
    for tok in exp_tokens:
        best = max(fuzz.ratio(tok, s) for s in span_tokens)
        if best >= 80:
            hit += len(tok)
    return hit / total


def _score(kind: str, expected: str, span_norm: str) -> tuple[float, float]:
    """Return (score 0..100, coverage of the span by the match 0..1)."""
    if not span_norm:
        return 0.0, 0.0
    if expected == span_norm:
        return 100.0, 1.0
    if kind == "partial":
        if len(span_norm) <= len(expected):
            # A short span must not "fully match" just by being a piece of the expected value.
            return fuzz.ratio(expected, span_norm), 1.0
        al = fuzz.partial_ratio_alignment(expected, span_norm)
        return al.score, (al.dest_end - al.dest_start) / len(span_norm)
    # token: every expected word must be present; extra label words lower coverage only.
    stripped = _PRODUCER_PREFIX.sub("", span_norm) or span_norm
    score = min(fuzz.token_set_ratio(expected, stripped), 100 * _token_recall(expected, stripped))
    coverage = min(1.0, len(expected) / len(stripped))
    return score, coverage


def match_text_field(
    field: str,
    expected_raw: str,
    label: LabelText,
    extracted_value: str | None,
    low_confidence: bool,
    pass_at: float,
    review_at: float,
    kind: str,
    t: Thresholds = THRESHOLDS,
) -> TextMatch:
    name = FIELD_LABELS[field]
    expected = normalize(expected_raw)
    rule = ("case/punctuation-insensitive match, fuzzy search" if kind == "partial"
            else "word-set match, all expected words required")

    def rank(c: tuple[float, float, Span]) -> tuple:
        score, coverage, span = c
        return (score >= pass_at and coverage >= t.line_coverage_min, score, coverage, -len(span.lines))

    candidates = [(*_score(kind, expected, span.norm), span) for span in label.spans]
    best = max(candidates, key=rank) if candidates else None

    details: dict = {"pass_at": pass_at, "review_at": review_at}

    # Vision provider: compare against the field it read; a disagreeing full-text hit is never a Pass.
    if extracted_value is not None:
        ext_score, _ = _score(kind, expected, normalize(extracted_value))
        details["score"] = round(ext_score, 1)
        found = clean(extracted_value)
        if ext_score >= pass_at:
            status, reason = Status.PASS, _pass_reason(expected_raw, found, name)
        elif ext_score >= review_at or low_confidence:
            status, reason = Status.NEEDS_REVIEW, f"The {name} on the label is close to, but not the same as, the application. Compare by eye."
        elif best and best[0] >= pass_at:
            status, reason = Status.NEEDS_REVIEW, f"The label's {name} reads \"{found}\", but the application value also appears elsewhere on the label. Compare by eye."
        else:
            status, reason = Status.FAIL, f"The label's {name} reads \"{found}\", which does not match the application."
        return TextMatch(FieldCheck(field=field, status=status, expected=expected_raw, found=found,
                                    rule=rule, reason=reason, details=details), None, 1.0)

    if best is None:
        status = Status.NEEDS_REVIEW if low_confidence else Status.FAIL
        reason = (f"Could not read the {name} on this image. Request a better image." if low_confidence
                  else f"The {name} was not found on the label.")
        return TextMatch(FieldCheck(field=field, status=status, expected=expected_raw, found=None,
                                    rule=rule, reason=reason, details=details), None, 0.0)

    score, coverage, span = best
    details.update(score=round(score, 1), line_coverage=round(coverage, 2))
    if score >= pass_at and coverage >= t.line_coverage_min:
        status, reason = Status.PASS, _pass_reason(expected_raw, span.text, name)
    elif score >= pass_at:
        status = Status.NEEDS_REVIEW
        reason = f"Found on the label but not confirmed as the {name} (it appears inside other text: \"{span.text}\")."
    elif score >= review_at:
        status = Status.NEEDS_REVIEW
        reason = f"Close but not an exact match to the application ({score:.0f}% similar). Compare by eye."
    elif low_confidence:
        status = Status.NEEDS_REVIEW
        reason = f"The {name} could not be confirmed; the image is hard to read. Request a better image."
    else:
        status = Status.FAIL
        reason = f"The application's {name} was not found on the label (closest text: \"{span.text}\")."
    found = span.text if score >= review_at else (span.text if status == Status.FAIL else None)
    return TextMatch(FieldCheck(field=field, status=status, expected=expected_raw, found=found,
                                rule=rule, reason=reason, details=details), span, coverage)


def _pass_reason(expected: str, found: str, name: str) -> str:
    if clean(expected) == found:
        return f"The {name} matches the application."
    return f"The {name} matches the application, ignoring capitalization and punctuation."


def resolve_shared_lines(matches: dict[str, TextMatch]) -> None:
    """A line can confirm only one field. If two passing fields claim the same line, the
    one that covers less of it is downgraded (e.g. brand words found only in the address)."""
    passing = {k: m for k, m in matches.items() if m.check.status == Status.PASS and m.span}
    for a, ma in passing.items():
        for b, mb in passing.items():
            if a == b or not set(ma.span.lines) & set(mb.span.lines):
                continue
            if ma.coverage < mb.coverage or (ma.coverage == mb.coverage and a == "brand_name"):
                ma.check.status = Status.NEEDS_REVIEW
                ma.check.reason = (f"Found on the label but not confirmed as the {FIELD_LABELS[a]}: "
                                   f"it is part of the {FIELD_LABELS[b]} line (\"{ma.span.text}\").")


def _canon_country(text: str) -> str:
    n = normalize(text)
    n = re.sub(r"^the ", "", n)
    return _COUNTRY_ALIASES.get(n, n)


def check_country(
    expected_raw: str | None,
    is_import: bool,
    label: LabelText,
    extracted_value: str | None,
    low_confidence: bool,
    t: Thresholds = THRESHOLDS,
) -> FieldCheck:
    rule = "country of origin statement (imports only)"
    if not is_import:
        return FieldCheck(field="country_of_origin", status=Status.NOT_APPLICABLE, expected=expected_raw,
                          found=None, rule=rule, reason="Not an import; country of origin not required.")
    if not expected_raw:
        return FieldCheck(field="country_of_origin", status=Status.NEEDS_REVIEW, expected=None, found=None,
                          rule=rule, reason="Marked as an import, but no country of origin was entered in the form.")
    expected = _canon_country(expected_raw)

    def fc(status: Status, found: str | None, reason: str) -> FieldCheck:
        return FieldCheck(field="country_of_origin", status=status, expected=expected_raw, found=found,
                          rule=rule, reason=reason)

    if extracted_value is not None:
        if fuzz.ratio(expected, _canon_country(extracted_value)) >= t.country_pass:
            return fc(Status.PASS, clean(extracted_value), "Country of origin matches the application.")
        return fc(Status.FAIL, clean(extracted_value),
                  f"The label gives the country of origin as \"{clean(extracted_value)}\", not \"{expected_raw}\".")

    statements: list[tuple[str, str]] = []  # (line text, country named)
    for span in label.spans:
        if len(span.lines) != 1:
            continue
        m = _COUNTRY_PREFIX.search(span.norm)
        if m:
            statements.append((span.text, m.group(1)))
    for text, country in statements:
        if fuzz.ratio(expected, _canon_country(country)) >= t.country_pass:
            return fc(Status.PASS, text, "Country of origin statement matches the application.")
    for span in label.spans:
        if len(span.lines) == 1 and fuzz.ratio(expected, _canon_country(span.norm)) >= t.country_pass:
            return fc(Status.PASS, span.text, "Country of origin appears on its own line and matches the application.")
    if statements:
        text, _ = statements[0]
        return fc(Status.FAIL, text, f"The label's country of origin (\"{text}\") does not match \"{expected_raw}\".")
    for span in label.spans:
        if len(span.lines) == 1 and fuzz.partial_ratio(expected, span.norm) >= t.country_pass and len(expected) >= 4:
            return fc(Status.NEEDS_REVIEW, span.text,
                      "The country name appears on the label but not as a country of origin statement. Check by eye.")
    if low_confidence:
        return fc(Status.NEEDS_REVIEW, None, "Could not find a country of origin; the image is hard to read.")
    return fc(Status.FAIL, None, "This is an import, but no country of origin statement was found on the label.")
