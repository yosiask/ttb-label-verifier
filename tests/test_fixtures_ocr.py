"""Every rendered fixture through real Tesseract and the full API path.

Expected results come from the fixture JSON, written by hand in scripts/make_fixtures.py.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.core.extractors.local_ocr import tesseract_available

FIXTURES = Path(__file__).parent / "fixtures"
CASES = sorted(p.stem for p in FIXTURES.glob("*.json"))

@pytest.fixture(autouse=True)
def no_rate_limit():
    from app.api import protection
    protection.reset_for_tests()


pytestmark = [pytest.mark.ocr, pytest.mark.skipif(not tesseract_available(), reason="Tesseract not installed")]
client = TestClient(app)


def as_list(v):
    return v if isinstance(v, list) else [v]


@pytest.mark.parametrize("case", CASES)
def test_fixture_local_ocr(case):
    meta = json.loads((FIXTURES / f"{case}.json").read_text())
    expected = meta["expected"]["local_ocr"]
    image = meta["image"]
    ctype = "image/jpeg" if image.endswith(".jpg") else "image/png"
    with open(FIXTURES / image, "rb") as f:
        r = client.post("/api/verify", files={"image": (image, f, ctype)},
                        data={"application": json.dumps(meta["application"]), "provider": "local"})
    assert r.status_code == 200, r.text
    body = r.json()
    got = {c["field"]: c["status"] for c in body["checks"]}
    assert body["overall"] in expected["overall"], (body["overall"], got)
    for field, want in expected["fields"].items():
        assert got[field] in as_list(want), (field, got[field], want)
    # Safeguard: a label expected to violate must never come back Pass.
    if "fail" in expected["overall"]:
        assert body["overall"] != "pass"


def test_fixture_set_is_complete():
    required = {"clean_spirits", "brand_case_diff", "brand_wrong", "abv_mismatch", "proof_inconsistent",
                "net_contents_units", "warning_title_case", "warning_missing_colon", "warning_altered_word",
                "warning_missing", "warning_body_bold", "brand_only_in_address", "import_no_country",
                "import_country_ok", "tilted_10deg", "dim", "glare", "blank_or_unreadable",
                "brand_one_letter_off", "blurry", "exif_rotated"}
    assert required <= set(CASES)
