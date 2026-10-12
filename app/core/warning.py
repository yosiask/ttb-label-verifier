"""Government health warning: canonical text and the strict check.

27 CFR 16.21 prescribes the exact wording. 27 CFR 16.22 requires "GOVERNMENT WARNING"
in capital letters and bold type, and the remainder of the statement not in bold.
Wording confirmed against the published regulation text on 12 Oct 2026.
"""

from __future__ import annotations

import difflib
import re

from rapidfuzz.distance import Levenshtein

from .config import THRESHOLDS, Thresholds
from .models import FieldCheck, Status
from .normalize import normalize_whitespace

CITATION = "27 CFR 16.21 / 16.22"
HEADING = "GOVERNMENT WARNING:"
CANONICAL_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
    "alcoholic beverages during pregnancy because of the risk of birth defects. "
    "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
    "operate machinery, and may cause health problems."
)
CANONICAL_WORDS = CANONICAL_WARNING.split()

_HEADING_LOOSE = re.compile(r"^\s*government\s+warning\s*([:;.,]?)", re.IGNORECASE)


def _rejoin_tokens(tokens: list[tuple[str, float | None]]) -> list[tuple[str, float | None]]:
    """Rejoin words hyphenated across a line break ("imp-", "airs" -> "impairs")."""
    out: list[tuple[str, float | None]] = []
    i = 0
    while i < len(tokens):
        word, conf = tokens[i]
        if word.endswith("-") and len(word) > 1 and i + 1 < len(tokens):
            nxt, nconf = tokens[i + 1]
            confs = [c for c in (conf, nconf) if c is not None]
            out.append((word[:-1] + nxt, min(confs) if confs else None))
            i += 2
            continue
        out.append((word, conf))
        i += 1
    return out


def _tokens_with_confidence(
    warning_text: str, word_confidences: list[tuple[str, float]]
) -> list[tuple[str, float | None]]:
    """Pair each warning word with its OCR confidence, if the provider gave any."""
    words = normalize_whitespace(warning_text.replace("-\n", "-")).split()
    if not word_confidences:
        return [(w, None) for w in words]
    ocr_words = [w for w, _ in word_confidences]
    # The extractor builds warning_text from a contiguous run of OCR words; find it.
    raw = warning_text.split()
    n = len(raw)
    for start in range(0, len(ocr_words) - n + 1):
        if ocr_words[start:start + n] == raw:
            return _rejoin_tokens([(w, c) for w, c in word_confidences[start:start + n]])
    return _rejoin_tokens([(w, None) for w in raw])


def word_diff(expected: list[str], found: list[str]) -> list[dict]:
    """Word-level diff for the UI: equal / missing / extra / changed segments."""
    ops = []
    sm = difflib.SequenceMatcher(a=expected, b=found, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            ops.append({"op": "equal", "text": " ".join(expected[i1:i2])})
        elif tag == "delete":
            ops.append({"op": "missing", "text": " ".join(expected[i1:i2])})
        elif tag == "insert":
            ops.append({"op": "extra", "text": " ".join(found[j1:j2])})
        else:
            ops.append({"op": "changed", "expected": " ".join(expected[i1:i2]), "found": " ".join(found[j1:j2])})
    return ops


def check_warning(
    warning_text: str | None,
    heading_bold: bool | None,
    body_bold: bool | None,
    word_confidences: list[tuple[str, float]],
    label_low_confidence: bool,
    t: Thresholds = THRESHOLDS,
) -> FieldCheck:
    steps: list[dict] = []

    def result(status: Status, reason: str, rule: str, found: str | None, **extra) -> FieldCheck:
        return FieldCheck(
            field="government_warning", status=status, expected=CANONICAL_WARNING, found=found,
            rule=rule, reason=reason, details={"citation": CITATION, "steps": steps, **extra},
        )

    # 1. Present
    if not warning_text or not warning_text.strip():
        if label_low_confidence:
            steps.append({"step": "present", "status": Status.NEEDS_REVIEW.value,
                          "reason": "Warning not read; image is hard to read."})
            return result(Status.NEEDS_REVIEW,
                          "Could not read a government warning on this image. Request a better image.",
                          "warning present", None)
        steps.append({"step": "present", "status": Status.FAIL.value, "reason": "No government warning found."})
        return result(Status.FAIL, "No government warning statement was found on the label.",
                      "warning present", None)
    steps.append({"step": "present", "status": Status.PASS.value, "reason": "Warning statement found."})

    tokens = _tokens_with_confidence(warning_text, word_confidences)
    found_words = [w for w, _ in tokens]
    found_text = " ".join(found_words)
    statuses: list[Status] = []

    def low_conf(idx: list[int]) -> bool:
        confs = [tokens[i][1] for i in idx if i < len(tokens)]
        return bool(confs) and all(c is not None and c < t.warning_noise_word_conf for c in confs)

    # 2. Heading: exactly "GOVERNMENT WARNING:" in capitals with a colon.
    heading_status, heading_reason = Status.PASS, "Heading reads exactly \"GOVERNMENT WARNING:\"."
    if not found_text.startswith(HEADING):
        m = _HEADING_LOOSE.match(found_text)
        if not m:
            heading_status = Status.FAIL
            heading_reason = "The statement does not begin with \"GOVERNMENT WARNING:\"."
        else:
            words_part = found_text[: m.end()].rstrip(":;., ")
            problems = []
            if words_part != "GOVERNMENT WARNING":
                problems.append(f"the heading reads \"{words_part}\"; it must be in capital letters")
            if m.group(1) != ":":
                problems.append("the colon after \"GOVERNMENT WARNING\" is missing")
            heading_status = Status.FAIL
            heading_reason = "Heading problem: " + " and ".join(problems) + "."
            # A missing colon or odd punctuation on a word OCR was unsure of may be a reading error.
            if words_part == "GOVERNMENT WARNING" and low_conf([0, 1]):
                heading_status = Status.NEEDS_REVIEW
                heading_reason += " The OCR was unsure of this text; compare by eye."
    steps.append({"step": "heading", "status": heading_status.value, "reason": heading_reason})
    statuses.append(heading_status)

    # 3. Wording: exact and case-sensitive after whitespace normalization.
    diff: list[dict] = []
    if found_words == CANONICAL_WORDS:
        wording_status, wording_reason = Status.PASS, "Wording matches the required text word for word."
    else:
        diff = word_diff(CANONICAL_WORDS, found_words)
        sm = difflib.SequenceMatcher(a=CANONICAL_WORDS, b=found_words, autojunk=False)
        opcodes = [op for op in sm.get_opcodes() if op[0] != "equal"]
        # Heading-only differences are already reported by step 2.
        opcodes_body = [op for op in opcodes if op[2] > 2 or (op[0] == "insert" and op[1] >= 2)]
        whole_word_change = any(tag in ("delete", "insert") or (i2 - i1) != (j2 - j1)
                                for tag, i1, i2, j1, j2 in opcodes_body)
        edits = 0
        affected: list[int] = []
        for tag, i1, i2, j1, j2 in opcodes_body:
            if tag == "replace" and (i2 - i1) == (j2 - j1):
                for a, b in zip(range(i1, i2), range(j1, j2)):
                    edits += Levenshtein.distance(CANONICAL_WORDS[a], found_words[b])
                    affected.append(b)
        if not opcodes_body:
            wording_status, wording_reason = Status.PASS, "Body wording matches the required text word for word."
        elif not whole_word_change and edits <= t.warning_noise_max_edits and low_conf(affected):
            wording_status = Status.NEEDS_REVIEW
            wording_reason = ("Possible reading error: a few letters differ in words the OCR was unsure of. "
                              "Compare the warning by eye.")
        else:
            wording_status = Status.FAIL
            wording_reason = _describe_diff(diff)
    steps.append({"step": "wording", "status": wording_status.value, "reason": wording_reason})
    statuses.append(wording_status)

    # 4. Bold: heading bold, body not bold. Unknown never counts as verified.
    if heading_bold is False or body_bold is True:
        bold_status = Status.FAIL
        parts = []
        if heading_bold is False:
            parts.append("\"GOVERNMENT WARNING:\" is not in bold type")
        if body_bold is True:
            parts.append("the rest of the warning is in bold type; it must not be")
        bold_reason = "Formatting problem: " + " and ".join(parts) + "."
    elif heading_bold is None or body_bold is None:
        bold_status = Status.NEEDS_REVIEW
        bold_reason = "Confirm by eye that \"GOVERNMENT WARNING:\" is bold and the rest is not (this engine cannot see type weight)."
    else:
        bold_status, bold_reason = Status.PASS, "Heading is bold and the rest is not."
    steps.append({"step": "bold", "status": bold_status.value, "reason": bold_reason})
    statuses.append(bold_status)

    step_reasons = list(zip(statuses, (heading_reason, wording_reason, bold_reason)))
    if Status.FAIL in statuses:
        overall = Status.FAIL
        reason = " ".join(r for s, r in step_reasons if s == Status.FAIL)
    elif Status.NEEDS_REVIEW in statuses:
        overall = Status.NEEDS_REVIEW
        if heading_status == Status.PASS and wording_status == Status.PASS:
            reason = "Wording verified; confirm \"GOVERNMENT WARNING:\" is bold and the rest is not."
        else:
            reason = " ".join(r for s, r in step_reasons if s == Status.NEEDS_REVIEW)
    else:
        overall, reason = Status.PASS, "Warning text is word for word correct, heading in capitals and bold, body not bold."

    return result(overall, reason, "exact wording, capitals, bold (27 CFR 16.21-16.22)", found_text, diff=diff)


def _describe_diff(diff: list[dict]) -> str:
    parts = []
    for d in diff:
        if d["op"] == "missing":
            parts.append(f"missing \"{d['text']}\"")
        elif d["op"] == "extra":
            parts.append(f"extra \"{d['text']}\"")
        elif d["op"] == "changed":
            parts.append(f"\"{d['found']}\" instead of \"{d['expected']}\"")
    shown = "; ".join(parts[:4]) + ("; ..." if len(parts) > 4 else "")
    return f"Warning wording differs from the required text: {shown}."
