import pytest

from app.core.models import Status
from app.core.rules.abv import check_alcohol, parse_alcohol


@pytest.mark.parametrize("text,abv,proof", [
    ("45%", [45.0], []),
    ("45% Alc./Vol. (90 Proof)", [45.0], [90.0]),
    ("Alc. 45% by vol", [45.0], []),
    ("ALC 12.5% BY VOL", [12.5], []),
    ("90 Proof", [], [90.0]),
    ("40 % ABV", [40.0], []),
    ("ABV 40", [40.0], []),
    ("37,5% vol", [37.5], []),
])
def test_parse(text, abv, proof):
    r = parse_alcohol(text)
    assert r.abv == abv and r.proof == proof


def test_bare_number_never_counts():
    r = parse_alcohol("Established 1845\nBatch 45\n750 mL")
    assert r.abv == [] and r.proof == []


def test_pass_and_mismatch():
    assert check_alcohol("45%", "45% Alc./Vol. (90 Proof)", "spirits", False).status == Status.PASS
    c = check_alcohol("45%", "40% Alc./Vol. (80 Proof)", "spirits", False)
    assert c.status == Status.FAIL and "40%" in c.reason


def test_proof_inconsistent_fails():
    c = check_alcohol("45%", "45% Alc./Vol. (80 Proof)", "spirits", False)
    assert c.status == Status.FAIL and "proof" in c.reason.lower()


def test_expected_proof_must_match():
    assert check_alcohol("45% (90 Proof)", "45% Alc./Vol.", "spirits", False).status == Status.PASS
    assert check_alcohol("90 Proof", "45% Alc./Vol.", "spirits", False).status == Status.PASS


def test_missing():
    assert check_alcohol("45%", "OLD TOM\n750 mL", "spirits", False).status == Status.FAIL
    assert check_alcohol("45%", "OLD TOM\n750 mL", "spirits", True).status == Status.NEEDS_REVIEW
    assert check_alcohol("12%", "CHATEAU X\n750 mL", "wine", False).status == Status.NEEDS_REVIEW
    # keyword present but number unreadable -> review, not fail
    assert check_alcohol("45%", "Alc. 4S by vol", "spirits", False).status == Status.NEEDS_REVIEW


def test_unparseable_application_value():
    assert check_alcohol("forty five", "45%", "spirits", False).status == Status.NEEDS_REVIEW
