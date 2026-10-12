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


@dataclass
class Score:
    score: float  # 0..100 fuzzy similarity, used only to choose Needs review vs Fail
    coverage: float  # share of the label line taken up by the match, 0..1
    exact: bool  # every expected word present exactly (after case/punctuation normalization)


def _contains_run(needle: list[str], hay: list[str]) -> bool:
    n = len(needle)
    return any(hay[i:i + n] == needle for i in range(len(hay) - n + 1))


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


def _score(kind: str, expected: str, span_norm: str) -> Score:
    """Compare normalized expected text with a normalized label span.

    Only an exact word match (ignoring case, punctuation and spacing) can lead to Pass.
    The fuzzy score decides between Needs review (a near miss, e.g. one letter off,
    which may be an OCR misread or a real spelling difference) and Fail.
    """
    if not span_norm:
        return Score(0.0, 0.0, False)
    if expected == span_norm:
        return Score(100.0, 1.0, True)
    exp_tokens = expected.split()
    if kind == "partial":
        span_tokens = span_norm.split()
        if _contains_run(exp_tokens, span_tokens):
            return Score(100.0, len(expected) / len(span_norm), True)
        # Same words with the spaces in different places, e.g. "STONESTHROW".
        if expected.replace(" ", "") == span_norm.replace(" ", ""):
            return Score(100.0, 1.0, True)
        if len(span_norm) <= len(expected):
            # A short span must not "fully match" just by being a piece of the expected value.
            return Score(fuzz.ratio(expected, span_norm), 1.0, False)
        al = fuzz.partial_ratio_alignment(expected, span_norm)
        return Score(al.score, (al.dest_end - al.dest_start) / len(span_norm), False)
    # token: every expected word must be present; extra label words lower coverage only.
    stripped = _PRODUCER_PREFIX.sub("", span_norm) or span_norm
    exact = set(exp_tokens) <= set(stripped.split())
    score = 100.0 if exact else min(fuzz.token_set_ratio(expected, stripped), 100 * _token_recall(expected, stripped))
    return Score(score, min(1.0, len(expected) / len(stripped)), exact)


def spelling_differences(expected_raw: str, found_raw: str) -> list[dict]:
    """Expected words that are not on the label exactly, with the closest label word."""
    found_words = [(w, normalize(w)) for w in clean(found_raw).split()]
    found_words = [(w, n) for w, n in found_words if n]
    found_norm = {n for _, n in found_words}
    diffs = []
    for word in clean(expected_raw).split():
        n = normalize(word)
        if not n or n in found_norm:
            continue
        closest = max(found_words, key=lambda fw: fuzz.ratio(n, fw[1]), default=None)
        if closest and fuzz.ratio(n, closest[1]) >= 60:
            diffs.append({"expected": word, "found": closest[0]})
        else:
            diffs.append({"expected": word, "found": None})
    return diffs


def _describe(diffs: list[dict]) -> str:
    parts = [f"\"{d['found']}\" instead of \"{d['expected']}\"" if d["found"] else f"\"{d['expected']}\" missing"
             for d in diffs[:3]]
    return "; ".join(parts) + ("; ..." if len(diffs) > 3 else "")


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
    rule = ("exact match ignoring capitalization and punctuation" if kind == "partial"
            else "all expected words present, ignoring capitalization and punctuation")

    def rank(c: tuple[Score, Span]) -> tuple:
        sc, span = c
        return (sc.exact and sc.coverage >= t.line_coverage_min, sc.exact, sc.score, sc.coverage, -len(span.lines))

    candidates = [(_score(kind, expected, span.norm), span) for span in label.spans]
    best = max(candidates, key=rank) if candidates else None

    details: dict = {"review_at": review_at}

    def near_miss(found: str, sc: Score) -> tuple[Status, str]:
        diffs = spelling_differences(expected_raw, found)
        details["spelling_differences"] = diffs
        what = _describe(diffs) if diffs else "the wording differs"
        lead = "Nearly matches" if sc.score >= pass_at else "Similar to the application"
        return Status.NEEDS_REVIEW, (f"{lead}, but the spelling is not the same ({what}). "
                                     "This may be a reading error or a real difference. Compare by eye.")

    # Vision provider: compare against the field it read; a disagreeing full-text hit is never a Pass.
    if extracted_value is not None:
        found = clean(extracted_value)
        sc = _score(kind, expected, normalize(extracted_value))
        details["score"] = round(sc.score, 1)
        if sc.exact and sc.coverage >= t.line_coverage_min:
            status, reason = Status.PASS, _pass_reason(expected_raw, found, name)
        elif sc.exact:
            status = Status.NEEDS_REVIEW
            reason = f"The label's {name} reads \"{found}\", which contains the application value plus other words. Compare by eye."
        elif sc.score >= review_at:
            status, reason = near_miss(found, sc)
        elif low_confidence:
            status, reason = Status.NEEDS_REVIEW, f"The {name} could not be confirmed; the image is hard to read."
        elif best and best[0].exact:
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

    sc, span = best
    details.update(score=round(sc.score, 1), line_coverage=round(sc.coverage, 2))
    if sc.exact and sc.coverage >= t.line_coverage_min:
        status, reason = Status.PASS, _pass_reason(expected_raw, span.text, name)
    elif sc.exact:
        status = Status.NEEDS_REVIEW
        reason = f"Found on the label but not confirmed as the {name} (it appears inside other text: \"{span.text}\")."
    elif sc.score >= review_at:
        status, reason = near_miss(span.text, sc)
    elif low_confidence:
        status = Status.NEEDS_REVIEW
        reason = f"The {name} could not be confirmed; the image is hard to read. Request a better image."
    else:
        status = Status.FAIL
        reason = f"The application's {name} was not found on the label (closest text: \"{span.text}\")."
    found = span.text if (sc.score >= review_at or status == Status.FAIL) else None
    return TextMatch(FieldCheck(field=field, status=status, expected=expected_raw, found=found,
                                rule=rule, reason=reason, details=details), span, sc.coverage)


def _pass_reason(expected: str, found: str, name: str) -> str:
    if clean(expected) == found:
        return f"The {name} matches the application."
    return f"The {name} matches the application (differences in capitalization or punctuation only)."


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
        named = _canon_country(_COUNTRY_PREFIX.sub(r"\1", normalize(extracted_value)))
        if named == expected:
            return fc(Status.PASS, clean(extracted_value), "Country of origin matches the application.")
        if fuzz.ratio(expected, named) >= t.country_review:
            return fc(Status.NEEDS_REVIEW, clean(extracted_value),
                      "Country of origin is spelled differently from the application. Compare by eye.")
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
        if _canon_country(country) == expected:
            return fc(Status.PASS, text, "Country of origin statement matches the application.")
    for span in label.spans:
        if len(span.lines) == 1 and _canon_country(span.norm) == expected:
            return fc(Status.PASS, span.text, "Country of origin appears on its own line and matches the application.")
    for text, country in statements:
        if fuzz.ratio(expected, _canon_country(country)) >= t.country_review:
            return fc(Status.NEEDS_REVIEW, text,
                      "Country of origin is spelled differently from the application. Compare by eye.")
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
