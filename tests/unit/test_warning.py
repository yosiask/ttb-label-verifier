import pytest

from app.core.models import Status
from app.core.warning import CANONICAL_WARNING, check_warning


def conf(text: str, value: float = 95.0, low_words: set[str] = frozenset()):
    return [(w, 40.0 if w in low_words else value) for w in text.split()]


def check(text, heading_bold=True, body_bold=False, confidences=None, low=False):
    return check_warning(text, heading_bold, body_bold,
                         conf(text) if confidences is None and text else (confidences or []), low)


def step(c, name):
    return next(s for s in c.details["steps"] if s["step"] == name)["status"]


def test_canonical_text_is_27_cfr_16_21():
    assert CANONICAL_WARNING.startswith("GOVERNMENT WARNING: (1) According to the Surgeon General,")
    assert CANONICAL_WARNING.endswith("operate machinery, and may cause health problems.")


def test_exact_with_bold_verified_passes():
    assert check(CANONICAL_WARNING).status == Status.PASS


def test_bold_unknown_is_needs_review_never_pass():
    c = check(CANONICAL_WARNING, heading_bold=None, body_bold=None)
    assert c.status == Status.NEEDS_REVIEW
    assert "bold" in c.reason
    assert step(c, "wording") == "pass"


def test_bold_violations_fail():
    assert check(CANONICAL_WARNING, heading_bold=False).status == Status.FAIL
    c = check(CANONICAL_WARNING, body_bold=True)
    assert c.status == Status.FAIL and "must not be" in c.reason


def test_title_case_heading_fails():
    c = check(CANONICAL_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:"), heading_bold=None, body_bold=None)
    assert c.status == Status.FAIL and "capital" in c.reason


def test_missing_colon_fails():
    c = check(CANONICAL_WARNING.replace("WARNING:", "WARNING"), heading_bold=None, body_bold=None)
    assert c.status == Status.FAIL and "colon" in c.reason


def test_missing_colon_on_low_confidence_word_is_review():
    text = CANONICAL_WARNING.replace("WARNING:", "WARNING")
    c = check(text, confidences=conf(text, low_words={"GOVERNMENT", "WARNING"}))
    assert c.status == Status.NEEDS_REVIEW


def test_altered_word_fails_with_diff():
    text = CANONICAL_WARNING.replace("cause health", "cause serious health")
    c = check(text)
    assert c.status == Status.FAIL
    assert {"op": "extra", "text": "serious"} in c.details["diff"]


def test_missing_words_fail():
    c = check(CANONICAL_WARNING.replace(" during pregnancy", ""))
    assert c.status == Status.FAIL
    assert {"op": "missing", "text": "during pregnancy"} in c.details["diff"]


def test_lowercase_body_word_fails():
    # Case-sensitive: "surgeon general" is a wording change, not cosmetic.
    assert check(CANONICAL_WARNING.replace("Surgeon General", "surgeon general")).status == Status.FAIL


def test_ocr_noise_low_confidence_is_review():
    text = CANONICAL_WARNING.replace("pregnancy", "pregnaney")
    c = check(text, confidences=conf(text, low_words={"pregnaney"}))
    assert c.status == Status.NEEDS_REVIEW and "reading error" in c.reason


def test_same_typo_with_high_confidence_fails():
    assert check(CANONICAL_WARNING.replace("pregnancy", "pregnaney")).status == Status.FAIL


def test_noise_rule_does_not_hide_large_edits():
    text = CANONICAL_WARNING.replace("pregnancy", "prgncy").replace("defects", "dfcts")
    c = check(text, confidences=conf(text, low_words={"prgncy", "dfcts"}))
    assert c.status == Status.FAIL  # 5 edits > 3


def test_line_break_hyphenation_rejoined():
    text = CANONICAL_WARNING.replace("impairs", "im-\npairs").replace("GOVERNMENT WARNING:", "GOVERNMENT\nWARNING:")
    assert check(text).status == Status.PASS


def test_missing_warning():
    assert check(None).status == Status.FAIL
    assert check(None, low=True).status == Status.NEEDS_REVIEW


def test_heading_absent_body_present_fails():
    c = check(CANONICAL_WARNING.replace("GOVERNMENT WARNING: ", ""), heading_bold=None, body_bold=None)
    assert c.status == Status.FAIL


def test_confident_punctuation_misread_is_review_not_fail():
    text = CANONICAL_WARNING.replace("General,", "General.").replace("machinery,", "machinery.")
    c = check(text)  # high OCR confidence on every word
    assert c.status == Status.NEEDS_REVIEW
    assert "punctuation" in c.reason.lower() and '"General." instead of "General,"' in c.reason


def test_punctuation_rule_does_not_hide_word_changes():
    text = CANONICAL_WARNING.replace("General,", "General.").replace("cause health", "cause serious health")
    assert check(text).status == Status.FAIL


def test_case_change_is_not_punctuation():
    assert check(CANONICAL_WARNING.replace("Consumption", "consumption")).status == Status.FAIL


def test_unknown_bold_reason_names_the_cause():
    from app.core.warning import CANONICAL_WARNING as W, check_warning

    ocr = check_warning(W, None, None, [], False)
    vision = check_warning(W, None, False, [], False, reader_sees_bold=True)
    assert ocr.status.value == vision.status.value == "needs_review"
    assert "cannot see type weight" in ocr.details["steps"][-1]["reason"]
    assert "could not tell" in vision.details["steps"][-1]["reason"]


@pytest.mark.parametrize("hb,bb,ratio,status,phrase", [
    (True, False, 1.8, "pass", "confirmed by measuring"),
    (True, False, None, "needs_review", "could not be measured"),  # the reader's word alone is not enough
    (True, False, 1.0, "needs_review", "same weight"),       # the live false-pass case
    (True, False, 1.27, "needs_review", "clearly heavier"),  # unsure band
    (False, False, 1.0, "fail", "not in bold"),
    (True, True, 1.0, "fail", "must not be"),
    (False, False, 1.8, "needs_review", "measure clearly heavier"),  # reader's defect contradicted
    (None, False, 1.0, "needs_review", "may not be bold"),
    (None, None, None, "needs_review", "could not tell"),
])
def test_bold_needs_pixels_and_reader_to_agree(hb, bb, ratio, status, phrase):
    from app.core.warning import CANONICAL_WARNING as W, check_warning

    r = check_warning(W, hb, bb, [], False, reader_sees_bold=True, weight_ratio=ratio)
    assert r.status.value == status
    assert phrase in r.reason or phrase in r.details["steps"][-1]["reason"], r.reason


def test_ocr_spacing_merges_are_not_wording_changes():
    text = CANONICAL_WARNING.replace("of the risk", "ofthe risk").replace("defects. (2)", "defects.(2)")
    assert check(text, confidences=conf(text)).status != Status.FAIL


def test_resplitting_never_hides_a_letter_change():
    text = CANONICAL_WARNING.replace("of the risk", "ofthe rlsk")
    assert check(text, confidences=conf(text)).status == Status.FAIL


@pytest.mark.parametrize("marker", ["[illegible]", "...", "…"])
def test_illegible_part_is_review_not_fail(marker):
    text = CANONICAL_WARNING.replace("risk of birth defects. (2) Consumption", f"ris{marker} consumption")
    r = check_warning(text, True, False, [], False, reader_sees_bold=True, weight_ratio=1.8)
    assert r.status == Status.NEEDS_REVIEW and "could not be read" in r.reason


def test_untrusted_ocr_reading_is_review_not_fail():
    text = CANONICAL_WARNING.replace("risk", "tisk").replace("operate", "(pert")
    r = check(text, confidences=conf(text, value=78.0))
    assert r.status == Status.NEEDS_REVIEW and "not confident" in r.reason


def test_confident_ocr_reading_of_an_altered_word_still_fails():
    text = CANONICAL_WARNING.replace("cause health", "cause serious health")
    assert check(text, confidences=conf(text, value=90.0)).status == Status.FAIL


def test_untrusted_ocr_never_passes():
    text = CANONICAL_WARNING.replace("risk", "tisk")
    assert check(text, confidences=conf(text, value=60.0)).status != Status.PASS


# --- Found on authentic TTB-approved labels (Public COLA Registry, scripts/make_registry_fixtures.py)

CAPS = "GOVERNMENT WARNING: " + CANONICAL_WARNING[len("GOVERNMENT WARNING: "):].upper()


def test_body_in_capitals_passes():
    # 27 CFR 16.22 sets the case of the heading only; most approved labels print the body in capitals.
    c = check(CAPS)
    assert c.status == Status.PASS and c.details["body_in_capitals"]


@pytest.mark.parametrize("old,new", [
    ("RISK OF", "RISKS OF"),            # Isolation Proof gin, approved
    ("YOUR ABILITY", "YOVUR ABILITY"),  # Cave City rum, approved
    ("DRIVE A CAR OR ", ""),            # Clearwater Light, approved
])
def test_capitals_body_still_checked_word_for_word(old, new):
    assert check(CAPS.replace(old, new)).status == Status.FAIL


def test_capitals_body_with_lowercase_heading_still_fails():
    c = check("Government Warning: " + CAPS[len("GOVERNMENT WARNING: "):])
    assert c.status == Status.FAIL and step(c, "heading") == "fail"


def test_mixed_case_body_stays_case_sensitive():
    # Only a body entirely in capitals is compared in capitals; one lowercased word is a change.
    text = CANONICAL_WARNING.replace("According to the Surgeon General", "ACCORDING TO THE SURGEON GENERAL")
    assert check(text).status == Status.FAIL


def test_space_before_heading_colon_is_spacing_only():
    c = check(CAPS.replace("WARNING:", "WARNING :", 1))
    assert step(c, "heading") == "pass" and c.status == Status.PASS


def test_capitals_ocr_merge_resplit():
    c = check(CAPS.replace("OF THE RISK", "OFTHE RISK"))
    assert step(c, "wording") == "pass"
