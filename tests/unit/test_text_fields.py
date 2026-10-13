from app.core.config import THRESHOLDS as T
from app.core.label_text import LabelText
from app.core.models import Status
from app.core.rules.text_fields import check_country, match_text_field, resolve_shared_lines
from app.core.warning import CANONICAL_WARNING


def brand(expected, text, extracted=None, low=False):
    return match_text_field("brand_name", expected, LabelText.from_full_text(text), extracted, low,
                            T.brand_pass, T.brand_review, "partial").check


def klass(expected, text, extracted=None):
    return match_text_field("class_type", expected, LabelText.from_full_text(text), extracted, False,
                            T.class_type_pass, T.class_type_review, "token").check


def test_cosmetic_difference_passes():
    c = brand("Stone's Throw", "STONE'S THROW\nKentucky Bourbon")
    assert c.status == Status.PASS and c.found == "STONE'S THROW"


def test_wrong_brand_fails():
    assert brand("BLUE HERON", "MAPLE CREEK\nKentucky Bourbon\n750 mL").status == Status.FAIL


def test_close_brand_needs_review():
    assert brand("OLD TOM DISTILLERY", "OLD TOM DISTILLING\n750 mL").status == Status.NEEDS_REVIEW


def test_wrong_brand_on_unreadable_label_is_review():
    assert brand("BLUE HERON", "MAPLE CREEK", low=True).status == Status.NEEDS_REVIEW


def test_brand_inside_other_line_not_confirmed():
    c = brand("STONE'S THROW", "RIVER BEND\nBottled by Stone's Throw Distillery, Frankfort, Kentucky")
    assert c.status == Status.NEEDS_REVIEW and "not confirmed" in c.reason


def test_short_fragment_is_not_full_match():
    # "STONE" is a piece of the expected brand; it must not score 100.
    assert brand("STONE'S THROW", "STONE\n750 mL").status != Status.PASS


def test_brand_in_warning_never_counts():
    text = "MAPLE CREEK\n" + CANONICAL_WARNING
    assert brand("Surgeon General", text).status == Status.FAIL


def test_class_type_requires_all_words():
    assert klass("Kentucky Straight Bourbon Whiskey", "OLD TOM\nWhiskey").status != Status.PASS
    assert klass("Kentucky Straight Bourbon Whiskey", "OLD TOM\nKENTUCKY STRAIGHT BOURBON WHISKEY").status == Status.PASS


def test_wrapped_value_matched_across_two_lines():
    c = match_text_field("producer_name_address", "Old Tom Distillery, Bardstown, Kentucky",
                         LabelText.from_full_text("OLD TOM\nDistilled by Old Tom Distillery,\nBardstown, Kentucky"),
                         None, False, T.producer_pass, T.producer_review, "token").check
    assert c.status == Status.PASS


def test_shared_line_downgrades_lower_coverage_field():
    label = LabelText.from_full_text("Stone's Throw Distillery, Frankfort, Kentucky")
    m = {
        "brand_name": match_text_field("brand_name", "Stone's Throw Distillery", label, None, False,
                                       T.brand_pass, T.brand_review, "partial"),
        "producer_name_address": match_text_field("producer_name_address", "Stone's Throw Distillery, Frankfort, Kentucky",
                                                  label, None, False, T.producer_pass, T.producer_review, "token"),
    }
    resolve_shared_lines(m)
    assert m["producer_name_address"].check.status == Status.PASS
    assert m["brand_name"].check.status == Status.NEEDS_REVIEW


def test_vision_field_disagreeing_with_full_text_hit_is_review():
    c = brand("STONE'S THROW", "RIVER BEND\nSTONE'S THROW", extracted="RIVER BEND")
    assert c.status == Status.NEEDS_REVIEW


def test_vision_field_match_passes():
    assert brand("Stone's Throw", "x", extracted="STONE'S THROW").status == Status.PASS


def country(expected, text, is_import=True, low=False):
    return check_country(expected, is_import, LabelText.from_full_text(text), None, low)


def test_country_rules():
    assert country("France", "x", is_import=False).status == Status.NOT_APPLICABLE
    assert country("Scotland", "GLEN X\nProduct of Scotland").status == Status.PASS
    assert country("USA", "GLEN X\nMade in the United States").status == Status.PASS
    assert country("Scotland", "GLEN X\nProduct of Ireland").status == Status.FAIL
    assert country("Scotland", "GLEN X\n750 mL").status == Status.FAIL
    assert country("Scotland", "GLEN X\n750 mL", low=True).status == Status.NEEDS_REVIEW
    assert country("France", "Imported by X Co., Paris, France").status == Status.NEEDS_REVIEW


# --- Cosmetic differences pass; spelling differences never pass automatically ---

import pytest  # noqa: E402


@pytest.mark.parametrize("label_brand", [
    "STONE'S THROW", "Stone’s Throw", "stone's throw", "STONES THROW", "Stone's-Throw", "STONE'S  THROW.",
    "STONESTHROW",
])
def test_cosmetic_variants_pass(label_brand):
    assert brand("Stone's Throw", f"{label_brand}\n750 mL").status == Status.PASS


@pytest.mark.parametrize("label_brand", [
    "OLD TOM DISTILERY",      # one letter missing (similarity 97)
    "OLD TOM DISTILLERIE",    # one letter changed
    "OLD TOMS DISTILLERY",    # one letter added
    "OLD TOM DISTILLING",
])
def test_one_letter_or_near_miss_is_review_not_pass(label_brand):
    c = brand("OLD TOM DISTILLERY", f"{label_brand}\n750 mL")
    assert c.status == Status.NEEDS_REVIEW
    assert "spelling" in c.reason
    assert c.details["spelling_differences"]


def test_spelling_difference_named_for_reviewer():
    c = brand("OLD TOM DISTILLERY", "OLD TOM DISTILERY\n750 mL")
    assert c.details["spelling_differences"] == [{"expected": "DISTILLERY", "found": "DISTILERY"}]
    assert '"DISTILERY" instead of "DISTILLERY"' in c.reason


def test_short_brand_one_letter_off_is_review():
    assert brand("ABSOLUT", "ABSOLUTE\n750 mL").status == Status.NEEDS_REVIEW


def test_brand_with_extra_words_on_its_line():
    # Exact words, but they cover too little of the line to confirm the field.
    assert brand("OLD TOM", "OLD TOM KENTUCKY STRAIGHT BOURBON WHISKEY").status == Status.NEEDS_REVIEW


def test_class_type_spelling_variant_is_review():
    assert klass("Blended Scotch Whisky", "GLEN X\nBlended Scotch Whiskey").status == Status.NEEDS_REVIEW


def test_producer_misspelling_is_review():
    c = match_text_field("producer_name_address", "Old Tom Distillery, Bardstown, Kentucky",
                         LabelText.from_full_text("OLD TOM\nDistilled by Old Tom Distilery, Bardstown, Kentucky"),
                         None, False, T.producer_pass, T.producer_review, "token").check
    assert c.status == Status.NEEDS_REVIEW


def test_vision_field_one_letter_off_is_review():
    assert brand("OLD TOM DISTILLERY", "x", extracted="OLD TOM DISTILERY").status == Status.NEEDS_REVIEW


def test_country_misspelling_is_review():
    assert country("Scotland", "GLEN X\nProduct of Scotlnd").status == Status.NEEDS_REVIEW


def test_vision_partial_brand_completed_on_label_passes():
    """Brand printed over two lines: the reader gave "OLD TOM", the label has the whole name."""
    r = brand("OLD TOM DISTILLERY", "OLD TOM\nDISTILLERY\nKentucky Straight Bourbon Whiskey", extracted="OLD TOM")
    assert r.status == Status.PASS


def test_vision_different_brand_with_app_value_elsewhere_is_still_review():
    text = "RIVER BEND\nBottled by Stone's Throw Distillery, Frankfort, Kentucky"
    r = brand("STONE'S THROW", text, extracted="RIVER BEND")
    assert r.status != Status.PASS


def test_brewed_and_canned_by_prefix_is_not_extra_wording():
    from app.core.rules.text_fields import match_text_field
    v = "Brewed and Canned by Iron Gate Brewing Co., Asheville, North Carolina"
    r = match_text_field("producer_name_address", "Iron Gate Brewing Co., Asheville, North Carolina",
                         LabelText.from_full_text("IRON GATE\n" + v), v, False, T.producer_pass, T.producer_review,
                         "token", T)
    assert r.check.status == Status.PASS
