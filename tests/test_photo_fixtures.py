"""Simulated label photographs (scripts/make_photo_fixtures.py): curvature, angle, glare,
blur, small print, unusual fonts, front/back labels. Safety properties, through real OCR:

- offline engine (real API): a violation, or a label whose right answer is Needs review,
  never comes back Pass;
- cloud path with a simulated perfect reader + real OCR cross-check: each verdict is one of
  the fixture's accepted answers;
- cloud path with a reader that reports the textbook warning and formatting whatever the
  label shows: no violation passes.
Live-model results on the same photos are in docs/validation-report.md (measured).
"""

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import protection
from app.api.main import app
from app.core.engine import verify
from app.core.extractors.crosscheck import CrossCheckedExtractor
from app.core.extractors.local_ocr import LocalOcrExtractor, tesseract_available
from app.core.models import ApplicationData, ExtractedLabel
from app.core.preprocess import load_image
from app.core.warning import CANONICAL_WARNING

PHOTOS = Path(__file__).parent / "fixtures" / "photos"
METAS = {p.stem: json.loads(p.read_text()) for p in sorted(PHOTOS.glob("*.json"))}
CASES = sorted(METAS)
NOT_COMPLIANT = [c for c in CASES if METAS[c]["truth"] != "compliant"]
pytestmark = [pytest.mark.ocr, pytest.mark.skipif(not tesseract_available(), reason="Tesseract not installed")]
client = TestClient(app)


def _digest(img) -> str:
    return hashlib.sha1(img.convert("RGB").tobytes()).hexdigest()


class SimulatedPanels:
    """Reads each panel of the fixture as a perfect transcriber would (or, with autocorrect,
    reports the standard warning text and formatting regardless of the label)."""
    name = "azure_vision"

    def __init__(self, meta: dict, autocorrect: bool = False):
        self.meta, self.autocorrect = meta, autocorrect
        self.panel_of = {}
        for name in meta["images"]:
            part = "full" if not ("_front." in name or "_back." in name) else name.rsplit("_", 1)[1].split(".")[0]
            self.panel_of[_digest(load_image((PHOTOS / name).read_bytes()))] = part

    def extract(self, image) -> ExtractedLabel:
        lab, part = self.meta["label"], self.panel_of[_digest(image)]
        front = part in ("full", "front")
        back = part in ("full", "back")
        warning = None
        if back and lab["warning"]:
            warning = CANONICAL_WARNING if self.autocorrect else f"{lab['heading']} {lab['body']}"
        lines = ([lab["brand"], lab["class_type"], lab["alcohol"], lab["net"]] if front else []) + \
                ([lab["producer"], lab["country"]] if back else [])
        lines = [x for x in lines if x]
        fields = {"brand_name": lab["brand"] if front else None, "class_type": lab["class_type"] if front else None,
                  "alcohol_content": lab["alcohol"] if front else None, "net_contents": lab["net"] if front else None,
                  "producer_name_address": lab["producer"] if back else None,
                  "country_of_origin": lab["country"] if back else None}
        return ExtractedLabel(
            provider="azure_vision", full_text="\n".join(lines + ([warning] if warning else [])), fields=fields,
            warning_text=warning,
            warning_heading_bold=(True if self.autocorrect else lab["heading_bold"]) if warning else None,
            warning_body_bold=(False if self.autocorrect else lab["body_bold"]) if warning else None,
            confidence=0.95, extraction_ms=0)


def run_sim(case: str, autocorrect: bool = False):
    meta = METAS[case]
    ex = CrossCheckedExtractor(SimulatedPanels(meta, autocorrect), LocalOcrExtractor(), allow_fallback=True)
    images = [(PHOTOS / n).read_bytes() for n in meta["images"]]
    return meta, verify(images, ApplicationData(**meta["application"]), ex, all_sides=meta["all_sides"])


@pytest.mark.parametrize("case", NOT_COMPLIANT)
def test_offline_never_passes_a_violation_photo(case):
    protection.reset_for_tests()
    meta = METAS[case]
    files = [("image", (n, (PHOTOS / n).read_bytes(), "image/jpeg")) for n in meta["images"]]
    r = client.post("/api/verify", files=files, data={
        "application": json.dumps(meta["application"]), "provider": "local",
        "all_sides": str(meta["all_sides"]).lower()})
    assert r.status_code == 200, r.text
    assert r.json()["overall"] != "pass"


@pytest.mark.parametrize("case", CASES)
def test_cloud_path_with_perfect_reader(case):
    meta, r = run_sim(case)
    expected = meta["expected"]["azure_vision"]
    got = {c.field: c.status.value for c in r.checks}
    assert r.overall.value in expected["overall"], (r.overall.value, got, r.message)
    for field, want in expected["fields"].items():
        assert got[field] in (want if isinstance(want, list) else [want]), (field, got[field], want)


@pytest.mark.parametrize("case", NOT_COMPLIANT)
def test_autocorrecting_reader_never_passes_a_violation_photo(case):
    _, r = run_sim(case, autocorrect=True)
    assert r.overall.value != "pass", [(c.field, c.status.value, c.reason) for c in r.checks]


def test_front_only_is_review_with_reason():
    meta, r = run_sim("front_only")
    w = next(c for c in r.checks if c.field == "government_warning")
    assert w.status.value == "needs_review" and "back label" in w.reason
