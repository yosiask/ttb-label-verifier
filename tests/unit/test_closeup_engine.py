"""Close-up re-read in the engine: a class/type Pass is held for review, nothing else changes."""

from app.core.engine import evaluate
from app.core.models import Status
from tests.conftest import make_label


def _class(application, label):
    checks, _ = evaluate(application, label)
    return next(c for c in checks if c.field == "class_type")


def test_closeup_variant_holds_class_pass_for_review(application):
    label = make_label().model_copy(update={"closeup_lines": ["KENTUCKY STRAIGT BOURBON WHISKEY"]})
    c = _class(application, label)
    assert c.status == Status.NEEDS_REVIEW and "STRAIGT" in c.reason


def test_closeup_from_cross_check_reader_counts(application):
    ocr = make_label().model_copy(update={"closeup_lines": ["KENTUCKY STRAIGHT BOURBUN WHISKEY"]})
    label = make_label(provider="azure_vision", word_confidences=[]).model_copy(update={"cross_check": ocr})
    assert _class(application, label).status == Status.NEEDS_REVIEW


def test_closeup_agreeing_keeps_pass(application):
    label = make_label().model_copy(update={"closeup_lines": ["KENTUCKY STRAIGHT BOURBON WHISKEY"]})
    assert _class(application, label).status == Status.PASS
