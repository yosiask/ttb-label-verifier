"""verify(): the provider reads the label, deterministic rules decide."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from .config import THRESHOLDS, Thresholds
from .extractors.base import LabelExtractor
from .label_text import LabelText
from .models import ApplicationData, ExtractedLabel, FieldCheck, ImageQuality, Status, VerificationResult
from .preprocess import load_image
from .quality import BLUR_BELOW, assess_quality, too_small_to_read
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
MAX_IMAGES = 4  # front, back, neck, side

# Each label image is read in its own worker; each of those may run two readers (cross-check).
_IMAGE_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="panel")


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
        cross_check_warning(
            check_warning(extracted.warning_text, extracted.warning_heading_bold, extracted.warning_body_bold,
                          extracted.word_confidences, low_conf, t,
                          reader_sees_bold=extracted.provider == "azure_vision",
                          weight_ratio=extracted.cross_check.warning_weight_ratio if extracted.cross_check else None),
            extracted.cross_check, t),
    ]

    if not readable:
        # Never Fail a label just because it could not be read.
        for c in checks:
            if c.status in (Status.FAIL, Status.PASS):
                c.details["status_before_unreadable"] = c.status.value
                c.status = Status.NEEDS_REVIEW
                c.reason = "The image is too hard to read to confirm this. Request a better image."
    return checks, readable


def _step(check: FieldCheck, name: str) -> str | None:
    return next((s["status"] for s in check.details.get("steps", []) if s["step"] == name), None)


def cross_check_warning(primary: FieldCheck, second: ExtractedLabel | None, t: Thresholds = THRESHOLDS) -> FieldCheck:
    """Compare the warning text from two independent readers.

    A vision model can "correct" an altered warning to the standard wording it knows, or
    imagine one that is not there. Offline OCR does not do that. If the two disagree about
    the text, the result is Needs review, never Pass. A bold-type failure is kept as Fail.
    """
    if second is None or second.confidence < t.unreadable_below:
        return primary
    other = check_warning(second.warning_text, None, None, second.word_confidences,
                          second.confidence < t.low_confidence_below, t)
    text_steps = ("present", "heading", "wording")
    p_ok = all(_step(primary, s) == Status.PASS.value for s in text_steps)
    o_ok = all(_step(other, s) == Status.PASS.value for s in text_steps)
    o_fail = any(_step(other, s) == Status.FAIL.value for s in text_steps)
    p_fail = any(_step(primary, s) == Status.FAIL.value for s in text_steps)
    bold_fail = _step(primary, "bold") == Status.FAIL.value

    summary = {"status": other.status.value, "reason": other.reason, "found": other.found,
               "diff": other.details.get("diff", [])}
    primary.details["cross_check"] = summary
    o_unsure = not o_ok and not o_fail  # e.g. OCR letter noise: cannot confirm the cloud's exact reading
    if p_ok and (o_fail or o_unsure):
        primary.status = Status.FAIL if bold_fail else Status.NEEDS_REVIEW
        primary.reason = ("The cloud reader saw the required wording, but the offline reader saw differences: "
                          f"{other.reason} Compare the warning by eye.")
        if bold_fail:
            primary.reason = f"{primary.reason} Also: {next(s['reason'] for s in primary.details['steps'] if s['step'] == 'bold')}"
        primary.details["readers_disagree"] = True
    elif p_fail and o_ok and not bold_fail:
        primary.status = Status.NEEDS_REVIEW
        primary.reason = (f"The cloud reader reported: {primary.reason} The offline reader saw the required wording "
                          "exactly. Compare the warning by eye.")
        primary.details["readers_disagree"] = True
    return primary


def merge_readings(readings: list[ExtractedLabel]) -> ExtractedLabel:
    """Combine the readings of several images of one label (front, back, ...) into one.

    Text from every image is searched. The warning, its bold judgment and its pixel weight
    come from one image: the one where the warning was read (the longest warning text), so a
    cross-check always compares the same panel. Readability is the weakest image's: a label
    is only as verified as its hardest-to-read panel.
    """
    if len(readings) == 1:
        return readings[0]
    w = max(range(len(readings)), key=lambda i: len(readings[i].warning_text or ""))
    panel = readings[w]
    fields: dict[str, str | None] = {}
    for r in readings:
        for k, v in r.fields.items():
            if fields.get(k) is None:
                fields[k] = v
    cross = [r.cross_check for r in readings]
    merged_cross = None
    if panel.cross_check is not None:
        present = [c for c in cross if c is not None]
        merged_cross = merge_readings(present).model_copy(update={
            "warning_text": panel.cross_check.warning_text,
            "warning_weight_ratio": panel.cross_check.warning_weight_ratio,
            "confidence": panel.cross_check.confidence,
        }) if len(present) > 1 else panel.cross_check
    usage: dict[str, int] = {}
    for r in readings:
        for k, v in (r.token_usage or {}).items():
            # Billed tokens add up; rate-limit headroom is the lowest seen.
            usage[k] = min(usage.get(k, v), v) if k.startswith("ratelimit_") else usage.get(k, 0) + v
    notes = [f"image {i + 1}: {n}" for i, r in enumerate(readings) for n in r.notes]
    fallbacks = [f"Image {i + 1}: {r.fallback_reason}" for i, r in enumerate(readings) if r.fallback_reason]
    providers = {r.provider for r in readings}
    return ExtractedLabel(
        provider=providers.pop() if len(providers) == 1 else panel.provider,
        full_text="\n".join(r.full_text for r in readings),
        fields=fields,
        warning_text=panel.warning_text,
        warning_heading_bold=panel.warning_heading_bold,
        warning_body_bold=panel.warning_body_bold,
        confidence=min(r.confidence for r in readings),
        word_confidences=[wc for r in readings for wc in r.word_confidences],
        extraction_ms=max(r.extraction_ms for r in readings),
        preprocess_ms=max(r.preprocess_ms for r in readings),
        notes=notes,
        cross_check=merged_cross,
        fallback_reason=" ".join(fallbacks) or None,
        warning_weight_ratio=panel.warning_weight_ratio,
        token_usage=usage or None,
    )


PARTIAL_LABEL_REASON = ("Not found on the uploaded image{s}. It may be on a side of the label that was not "
                        "uploaded (for example the back label). Upload every side, or, if {these} show{verb} the "
                        "whole label, tick \"These images show every side of the label\".")


def soften_absences(checks: list[FieldCheck], n_images: int) -> None:
    """When the uploaded images may not show every side of the label, something missing is
    not proof of a violation: it may be on the back. Absent → Needs review; a statement that
    is present but wrong is still Fail."""
    for c in checks:
        if c.status == Status.FAIL and (c.found is None or c.details.get("absent")):
            c.details["status_if_all_sides"] = c.status.value
            c.status = Status.NEEDS_REVIEW
            c.reason = PARTIAL_LABEL_REASON.format(s="s" if n_images > 1 else "", these="these" if n_images > 1 else "it",
                                                   verb="" if n_images > 1 else "s")


def _read_one(data: bytes, extractor: LabelExtractor) -> tuple[ExtractedLabel, ImageQuality, int]:
    t0 = time.perf_counter()
    image = load_image(data)
    quality = assess_quality(image)
    decode_ms = int((time.perf_counter() - t0) * 1000)
    extracted = extractor.extract(image)
    if extracted.cross_check is not None and quality.sharpness < BLUR_BELOW:
        # Blur thickens every stroke alike, so the weight measurement says nothing on a blurry photo.
        extracted = extracted.model_copy(update={
            "cross_check": extracted.cross_check.model_copy(update={"warning_weight_ratio": None})})
    if too_small_to_read(quality):
        extracted = extracted.model_copy(update={"confidence": 0.0})
    return extracted, quality, decode_ms


def verify(images: bytes | list[bytes], application: ApplicationData, extractor: LabelExtractor,
           t: Thresholds = THRESHOLDS, all_sides: bool = True) -> VerificationResult:
    """Check one label, given one or more images of it (front, back, ...).

    all_sides: the images show every side of the label, so anything not found is missing
    from the label (Fail). When False, absences are Needs review.
    """
    images = [images] if isinstance(images, bytes) else list(images)
    t0 = time.perf_counter()
    if len(images) == 1:
        results = [_read_one(images[0], extractor)]
    else:
        futures = [_IMAGE_POOL.submit(_read_one, d, extractor) for d in images]
        results = [f.result() for f in futures]  # the first error (e.g. an unreadable file) is raised
    readings = [r[0] for r in results]
    qualities = [r[1] for r in results]
    extracted = merge_readings(readings)
    t2 = time.perf_counter()
    checks, readable = evaluate(application, extracted, t)
    if not all_sides:
        soften_absences(checks, len(images))
    t3 = time.perf_counter()

    overall = _overall(checks)
    notes = []
    if extracted.fallback_reason:
        notes.append(extracted.fallback_reason)
    if not readable:
        overall = Status.NEEDS_REVIEW
        notes.insert(0, UNREADABLE_MESSAGE)
    if extracted.notes:
        notes.append("Reader notes: " + "; ".join(extracted.notes) + ".")
    for i, q in enumerate(qualities):
        if q.issues:
            prefix = f"Image {i + 1}: " if len(qualities) > 1 else ""
            notes.append(prefix + " ".join(q.issues))

    timings = {
        "decode": max(r[2] for r in results),
        "preprocess": extracted.preprocess_ms,
        "extract": extracted.extraction_ms,
        "rules": int((t3 - t2) * 1000),
        "total": int((t3 - t0) * 1000),
    }
    if extracted.cross_check:
        timings["cross_check"] = extracted.cross_check.extraction_ms + extracted.cross_check.preprocess_ms
    worst = min(qualities, key=lambda q: (len(q.issues) == 0, q.sharpness))
    return VerificationResult(
        overall=overall,
        checks=checks,
        not_checked=NOT_CHECKED,
        image_readable=readable,
        provider=extracted.provider,
        message=" ".join(notes) or None,
        image_quality=worst,
        image_count=len(images),
        all_sides=all_sides,
        timings_ms=timings,
        token_usage=extracted.token_usage,
    )
