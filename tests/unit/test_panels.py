"""Several images of one label (front, back, ...) and the 'every side uploaded' rule."""

from app.core.engine import merge_readings, verify
from app.core.models import ApplicationData, Status
from app.core.warning import CANONICAL_WARNING
from tests.conftest import LABEL_TEXT, make_label, text_png

FRONT_TEXT = "OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n45% Alc./Vol. (90 Proof)\n750 mL"
BACK_TEXT = "Distilled and Bottled by Old Tom Distillery, Bardstown, Kentucky"
APP = ApplicationData(brand_name="OLD TOM DISTILLERY", class_type="Kentucky Straight Bourbon Whiskey",
                      alcohol_content="45% Alc./Vol. (90 Proof)", net_contents="750 mL",
                      producer_name_address="Old Tom Distillery, Bardstown, Kentucky")


def png(color="white") -> bytes:
    return text_png(color)


class PanelReader:
    """Returns the front reading for a white image and the back reading for an ivory one."""
    name = "azure_vision"

    def __init__(self, front, back):
        self.front, self.back = front, back

    def extract(self, image):
        return self.front if image.getpixel((0, 0)) == (255, 255, 255) else self.back


def front(**kw):
    return make_label(text=FRONT_TEXT, warning=None, provider="azure_vision", **kw)


def back(**kw):
    kw.setdefault("heading_bold", True)
    kw.setdefault("body_bold", False)
    # The offline cross-check of this panel measured a bold heading over a regular body.
    kw.setdefault("cross_check", make_label(text=BACK_TEXT, warning_weight_ratio=1.8))
    return make_label(text=BACK_TEXT, provider="azure_vision", **kw)


def field(r, name):
    return next(c for c in r.checks if c.field == name)


def test_front_and_back_together_pass():
    r = verify([png(), png("ivory")], APP, PanelReader(front(), back()), all_sides=True)
    assert r.overall == Status.PASS and r.image_count == 2, [(c.field, c.status, c.reason) for c in r.checks]


def test_front_only_missing_warning_is_review_not_fail():
    r = verify([png()], APP, PanelReader(front(), back()), all_sides=False)
    w = field(r, "government_warning")
    assert w.status == Status.NEEDS_REVIEW and "back label" in w.reason
    assert w.details["status_if_all_sides"] == "fail"
    assert field(r, "producer_name_address").status == Status.NEEDS_REVIEW  # also on the back
    assert r.overall == Status.NEEDS_REVIEW


def test_missing_warning_fails_when_every_side_was_uploaded():
    r = verify([png()], APP, PanelReader(front(), back()), all_sides=True)
    assert field(r, "government_warning").status == Status.FAIL and r.overall == Status.FAIL


def test_wrong_statement_still_fails_on_a_partial_label():
    """Only absences are softened: a warning that is present but wrong is a violation either way."""
    title = CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:")
    bad = back(warning=title, cross_check=make_label(text=BACK_TEXT, warning=title, warning_weight_ratio=1.8))
    r = verify([png(), png("ivory")], APP, PanelReader(front(), bad), all_sides=False)
    assert field(r, "government_warning").status == Status.FAIL


def test_mismatch_on_front_still_fails_on_a_partial_label():
    wrong = make_label(text=FRONT_TEXT.replace("45%", "40%").replace("90 Proof", "80 Proof"), warning=None,
                       provider="azure_vision")
    r = verify([png()], APP, PanelReader(wrong, back()), all_sides=False)
    assert field(r, "alcohol_content").status == Status.FAIL and r.overall == Status.FAIL


def test_warning_and_bold_come_from_the_panel_that_has_the_warning():
    m = merge_readings([front(heading_bold=False, body_bold=True), back()])
    assert m.warning_text == CANONICAL_WARNING
    assert m.warning_heading_bold is True and m.warning_body_bold is False
    assert m.full_text.startswith("OLD TOM") and BACK_TEXT in m.full_text


def test_weakest_panel_sets_readability():
    m = merge_readings([front(confidence=0.95), back(confidence=0.4)])
    assert m.confidence == 0.4


def test_token_usage_and_notes_are_combined():
    m = merge_readings([front(token_usage={"prompt_tokens": 10, "completion_tokens": 2}, notes=["glare"]),
                        back(token_usage={"prompt_tokens": 20, "completion_tokens": 3})])
    assert m.token_usage == {"prompt_tokens": 30, "completion_tokens": 5}
    assert m.notes == ["image 1: glare"]


def test_single_image_default_is_unchanged():
    r = verify(png(), APP, PanelReader(make_label(text=LABEL_TEXT, heading_bold=True, body_bold=False,
                                                  provider="azure_vision",
                                                  cross_check=make_label(warning_weight_ratio=1.8)), None))
    assert r.overall == Status.PASS and r.all_sides is True


def test_hard_to_read_front_only_mentions_the_back_label():
    blurry_front = make_label(text=FRONT_TEXT, warning=None, provider="azure_vision", confidence=0.6)
    r = verify([png()], APP, PanelReader(blurry_front, back()), all_sides=False)
    w = field(r, "government_warning")
    assert w.status == Status.NEEDS_REVIEW and "back label" in w.reason
