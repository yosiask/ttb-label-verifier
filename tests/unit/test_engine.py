import io

import pytest
from PIL import Image

from app.core.engine import evaluate, verify
from app.core.models import Status
from app.core.preprocess import InvalidImageError
from app.core.warning import CANONICAL_WARNING
from tests.conftest import LABEL_TEXT, FakeExtractor, make_label


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, "PNG")
    return buf.getvalue()


def statuses(checks):
    return {c.field: c.status for c in checks}


def test_ocr_clean_label_is_review_for_bold_only(application):
    checks, readable = evaluate(application, make_label())
    s = statuses(checks)
    assert readable
    assert s.pop("government_warning") == Status.NEEDS_REVIEW
    assert s.pop("country_of_origin") == Status.NOT_APPLICABLE
    assert set(s.values()) == {Status.PASS}


def test_overall_pass_requires_bold_verified(application):
    r = verify(png(), application, FakeExtractor(make_label(heading_bold=True, body_bold=False)))
    assert r.overall == Status.PASS


def test_any_fail_makes_overall_fail(application):
    label = make_label(LABEL_TEXT.replace("45%", "40%").replace("90 Proof", "80 Proof"), heading_bold=True, body_bold=False)
    r = verify(png(), application, FakeExtractor(label))
    assert r.overall == Status.FAIL


def test_unreadable_never_fails(application):
    label = make_label("MAPLE CREEK", warning=None, confidence=0.3)
    r = verify(png(), application, FakeExtractor(label))
    assert r.overall == Status.NEEDS_REVIEW and not r.image_readable
    assert "better image" in r.message
    assert Status.FAIL not in {c.status for c in r.checks}


def test_timings_reported(application):
    r = verify(png(), application, FakeExtractor(make_label()))
    assert set(r.timings_ms) == {"decode", "preprocess", "extract", "rules", "total"}


def test_extractor_never_sees_application(application):
    """Extraction is blind: extract() takes only the image."""
    import inspect

    from app.core.extractors.local_ocr import LocalOcrExtractor
    assert list(inspect.signature(LocalOcrExtractor.extract).parameters) == ["self", "image"]


def test_bad_image_bytes_rejected(application):
    with pytest.raises(InvalidImageError):
        verify(b"not an image", application, FakeExtractor(make_label()))


def test_gif_rejected(application):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, "GIF")
    with pytest.raises(InvalidImageError):
        verify(buf.getvalue(), application, FakeExtractor(make_label()))


def test_warning_words_do_not_satisfy_fields(application):
    application.class_type = "alcoholic beverages"
    checks, _ = evaluate(application, make_label("OLD TOM DISTILLERY\n750 mL", warning=CANONICAL_WARNING))
    assert statuses(checks)["class_type"] == Status.FAIL
