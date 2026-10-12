import pytest

from app.core.models import Status
from app.core.rules.net_contents import check_net_contents, parse_volumes


@pytest.mark.parametrize("text,ml", [
    ("750 mL", 750), ("750ml", 750), ("75 cL", 750), ("75cl", 750), ("1.75 L", 1750), ("1 Liter", 1000),
    ("1,75 L", 1750), ("25.4 FL. OZ.", 751.2), ("12 fl oz", 354.9), ("1,000 mL", 1000), ("750 millilitres", 750),
])
def test_parse(text, ml):
    assert parse_volumes(text)[0][0] == pytest.approx(ml, rel=1e-3)


def test_bare_number_never_counts():
    assert parse_volumes("Batch 750\nEst. 1845") == []


def test_units_converted():
    c = check_net_contents("750 mL", "75 cL", False)
    assert c.status == Status.PASS and "750 mL" in c.reason


def test_tolerance():
    assert check_net_contents("750 mL", "25.4 fl oz", False).status == Status.PASS  # 751.2 mL, within 0.5%
    assert check_net_contents("750 mL", "700 mL", False).status == Status.FAIL


def test_missing():
    assert check_net_contents("750 mL", "OLD TOM\n45%", False).status == Status.FAIL
    assert check_net_contents("750 mL", "OLD TOM\n45%", True).status == Status.NEEDS_REVIEW
    assert check_net_contents("750 mL", "7S0 mL", False).status == Status.NEEDS_REVIEW
