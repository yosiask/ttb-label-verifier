"""verify(): the provider reads the label, deterministic rules decide."""

from __future__ import annotations

import time

from .config import THRESHOLDS, Thresholds
from .extractors.base import LabelExtractor
from .label_text import LabelText
from .models import ApplicationData, ExtractedLabel, FieldCheck, Status, VerificationResult
from .preprocess import load_image
from .rules.abv import check_alcohol
from .rules.net_contents import check_net_contents
from .rules.text_fields import check_country, match_text_field, resolve_shared_lines
from .warning import check_warning

NOT_CHECKED = [
    "Government warning type size (27 CFR 16.22(b): 1 mm, 2 mm or 3 mm depending on container size).",
    "Whether the warning is readily legible, on a contrasting background, and separate and apart from other text.",
    "Placement of statements on the label (same field of vision, brand label vs back label).",
    "Mandatory statements not in this form (e.g. sulfite, colouring or age statements).",
]

UNREADABLE_MESSAGE = "We couldn't read this label clearly. Request a better image."


def _overall(checks: list[FieldCheck]) -> Status:
    statuses = {c.status for c in checks}
    if Status.FAIL in statuses:
        return Status.FAIL
    if Status.NEEDS_REVIEW in statuses:
        return Status.NEEDS_REVIEW
    return Status.PASS


def evaluate(application: ApplicationData, extracted: ExtractedLabel, t: Thresholds = THRESHOLDS) -> tuple[list[FieldCheck], bool]:
    """Apply every rule to what was read. Returns the checks and whether the image was readable."""
    readable = extracted.confidence >= t.unreadable_below and bool(extracted.full_text.strip())
    low_conf = extracted.confidence < t.low_confidence_below
    label = LabelText.from_full_text(extracted.full_text)
    f = extracted.fields

    matches = {
        "brand_name": match_text_field("brand_name", application.brand_name, label, f.get("brand_name"),
                                       low_conf, t.brand_pass, t.brand_review, "partial", t),
        "class_type": match_text_field("class_type", application.class_type, label, f.get("class_type"),
                                       low_conf, t.class_type_pass, t.class_type_review, "token", t),
        "producer_name_address": match_text_field(
            "producer_name_address", application.producer_name_address, label,
            f.get("producer_name_address"), low_conf, t.producer_pass, t.producer_review, "token", t),
    }
    resolve_shared_lines(matches)

    checks = [
        matches["brand_name"].check,
        matches["class_type"].check,
        check_alcohol(application.alcohol_content, label.non_warning_text, application.beverage_type,
                      low_conf, f.get("alcohol_content"), t),
        check_net_contents(application.net_contents, label.non_warning_text, low_conf, f.get("net_contents"), t),
        matches["producer_name_address"].check,
        check_country(application.country_of_origin, application.is_import, label,
                      f.get("country_of_origin"), low_conf, t),
        check_warning(extracted.warning_text, extracted.warning_heading_bold, extracted.warning_body_bold,
                      extracted.word_confidences, low_conf, t),
    ]

    if not readable:
        # Never Fail a label just because it could not be read.
        for c in checks:
            if c.status in (Status.FAIL, Status.PASS):
                c.details["status_before_unreadable"] = c.status.value
                c.status = Status.NEEDS_REVIEW
                c.reason = "The image is too hard to read to confirm this. Request a better image."
    return checks, readable


def verify(image_bytes: bytes, application: ApplicationData, extractor: LabelExtractor,
           t: Thresholds = THRESHOLDS) -> VerificationResult:
    t0 = time.perf_counter()
    image = load_image(image_bytes)
    t1 = time.perf_counter()
    extracted = extractor.extract(image)
    t2 = time.perf_counter()
    checks, readable = evaluate(application, extracted, t)
    t3 = time.perf_counter()

    overall = _overall(checks)
    message = None
    if not readable:
        overall, message = Status.NEEDS_REVIEW, UNREADABLE_MESSAGE
    elif extracted.notes:
        message = "Image adjusted before reading: " + "; ".join(extracted.notes) + "."

    return VerificationResult(
        overall=overall,
        checks=checks,
        not_checked=NOT_CHECKED,
        image_readable=readable,
        provider=extracted.provider,
        message=message,
        timings_ms={
            "decode": int((t1 - t0) * 1000),
            "preprocess": extracted.preprocess_ms,
            "extract": extracted.extraction_ms,
            "rules": int((t3 - t2) * 1000),
            "total": int((t3 - t0) * 1000),
        },
    )
