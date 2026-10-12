import time

import pytest
from PIL import Image

from app.core.engine import evaluate
from app.core.extractors.azure_vision import ProviderTimeoutError
from app.core.extractors.base import ProviderUnavailableError
from app.core.extractors.crosscheck import CrossCheckedExtractor
from app.core.models import Status
from app.core.warning import CANONICAL_WARNING
from tests.conftest import FakeExtractor, make_label

ALTERED = CANONICAL_WARNING.replace("cause health", "cause serious health")


class Failing:
    name = "azure_vision"

    def __init__(self, error):
        self.error = error

    def extract(self, image):
        raise self.error


def vision(warning=CANONICAL_WARNING, heading_bold=True, body_bold=False):
    return make_label(warning=warning, provider="azure_vision", heading_bold=heading_bold, body_bold=body_bold,
                      word_confidences=[])


def warning_check(application, label):
    checks, _ = evaluate(application, label)
    return next(c for c in checks if c.field == "government_warning")


IMG = Image.new("RGB", (800, 600), "white")


def test_cross_check_attached():
    ex = CrossCheckedExtractor(FakeExtractor(vision()), FakeExtractor(make_label()), allow_fallback=True)
    r = ex.extract(IMG)
    assert r.provider == "azure_vision" and r.cross_check.provider == "local_ocr"


def test_timeout_falls_back_to_offline_when_allowed():
    ex = CrossCheckedExtractor(Failing(ProviderTimeoutError("The cloud AI engine did not answer within 8 seconds.")),
                               FakeExtractor(make_label()), allow_fallback=True)
    r = ex.extract(IMG)
    assert r.provider == "local_ocr"
    assert "8 seconds" in r.fallback_reason and "offline engine" in r.fallback_reason


def test_no_fallback_when_cloud_explicitly_chosen():
    ex = CrossCheckedExtractor(Failing(ProviderUnavailableError("down")), FakeExtractor(make_label()),
                               allow_fallback=False)
    with pytest.raises(ProviderUnavailableError):
        ex.extract(IMG)


def test_readers_run_in_parallel():
    class Slow(FakeExtractor):
        def extract(self, image):
            time.sleep(0.3)
            return super().extract(image)
    ex = CrossCheckedExtractor(Slow(vision()), Slow(make_label()), allow_fallback=True)
    t = time.perf_counter()
    ex.extract(IMG)
    assert time.perf_counter() - t < 0.55


# --- the safeguard: a vision model "correcting" an altered warning ---

def test_vision_autocorrect_caught_by_ocr(application):
    label = vision().model_copy(update={"cross_check": make_label(warning=ALTERED)})
    c = warning_check(application, label)
    assert c.status == Status.NEEDS_REVIEW
    assert c.details["readers_disagree"] and "serious" in c.reason


def test_vision_hallucinated_warning_caught_when_ocr_finds_none(application):
    label = vision().model_copy(update={"cross_check": make_label(warning=None)})
    assert warning_check(application, label).status == Status.NEEDS_REVIEW


def test_agreeing_readers_pass(application):
    label = vision().model_copy(update={"cross_check": make_label()})
    c = warning_check(application, label)
    assert c.status == Status.PASS and "readers_disagree" not in c.details


def test_agreeing_violation_fails(application):
    label = vision(warning=ALTERED).model_copy(update={"cross_check": make_label(warning=ALTERED)})
    assert warning_check(application, label).status == Status.FAIL


def test_vision_misread_vs_exact_ocr_is_review_not_fail(application):
    title = CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")
    label = vision(warning=title).model_copy(update={"cross_check": make_label()})
    assert warning_check(application, label).status == Status.NEEDS_REVIEW


def test_bold_failure_kept_even_when_readers_disagree(application):
    label = vision(body_bold=True).model_copy(update={"cross_check": make_label(warning=ALTERED)})
    assert warning_check(application, label).status == Status.FAIL


def test_unreadable_ocr_does_not_override(application):
    label = vision().model_copy(update={"cross_check": make_label(warning=ALTERED, confidence=0.3)})
    assert warning_check(application, label).status == Status.PASS


def test_vision_small_letter_difference_is_review(application):
    """No per-word confidence from vision: a few letters off could be a misread."""
    label = vision(warning=CANONICAL_WARNING.replace("pregnancy", "pregnancey"))
    assert warning_check(application, label).status == Status.NEEDS_REVIEW
