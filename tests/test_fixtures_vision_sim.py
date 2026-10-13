"""The cloud-vision path through the engine, on every fixture, without calling Azure.

A *simulated* vision reader returns exactly what was rendered (from the fixture's
"label" block), and real offline OCR runs alongside it as the cross-check. This tests
the rules and safeguards on the vision path; it says nothing about the real model's
accuracy, which is measured against Azure once the deployment is approved.
"""

import json
from pathlib import Path

import pytest

from app.core.engine import verify
from app.core.extractors.crosscheck import CrossCheckedExtractor
from app.core.extractors.local_ocr import LocalOcrExtractor, tesseract_available
from app.core.models import ApplicationData, ExtractedLabel
from app.core.warning import CANONICAL_WARNING

FIXTURES = Path(__file__).parent / "fixtures"
CASES = sorted(p.stem for p in FIXTURES.glob("*.json"))
pytestmark = [pytest.mark.ocr, pytest.mark.skipif(not tesseract_available(), reason="Tesseract not installed")]


class SimulatedVision:
    name = "azure_vision"

    def __init__(self, meta: dict, autocorrect_warning: bool = False):
        self.meta, self.autocorrect = meta, autocorrect_warning

    def extract(self, image) -> ExtractedLabel:
        lab = self.meta["label"]
        if (self.meta.get("degradation") or [None])[0] == "blank":
            return ExtractedLabel(provider="azure_vision", full_text="", fields={}, warning_text=None,
                                  warning_heading_bold=None, warning_body_bold=None, confidence=0.2,
                                  extraction_ms=0, notes=["No label text visible"])
        warning = CANONICAL_WARNING if self.autocorrect else lab["warning"]
        lines = [lab["brand"], lab["class_type"], lab["alcohol"], lab["net"], lab["producer"], lab.get("country")]
        lines = [x for x in lines if x]
        return ExtractedLabel(
            provider="azure_vision",
            full_text="\n".join(lines + ([warning] if warning else [])),
            fields={"brand_name": lab["brand"], "class_type": lab["class_type"], "alcohol_content": lab["alcohol"],
                    "net_contents": lab["net"], "producer_name_address": lab["producer"],
                    "country_of_origin": lab.get("country")},
            warning_text=warning,
            # Autocorrecting also reports textbook formatting, as the live model did 1 time in 5 on a
            # regular-weight heading (2026-10-13).
            warning_heading_bold=(True if self.autocorrect else lab["heading_bold"]) if warning else None,
            warning_body_bold=(False if self.autocorrect else lab["body_bold"]) if warning else None,
            confidence=0.95, extraction_ms=0,
        )


def run(case: str, autocorrect: bool = False):
    meta = json.loads((FIXTURES / f"{case}.json").read_text())
    ex = CrossCheckedExtractor(SimulatedVision(meta, autocorrect), LocalOcrExtractor(), allow_fallback=True)
    image = (FIXTURES / meta["image"]).read_bytes()
    return meta, verify(image, ApplicationData(**meta["application"]), ex)


def as_list(v):
    return v if isinstance(v, list) else [v]


@pytest.mark.parametrize("case", CASES)
def test_fixture_vision_path(case):
    meta, r = run(case)
    expected = meta["expected"]["azure_vision"]
    got = {c.field: c.status.value for c in r.checks}
    assert r.overall.value in expected["overall"], (r.overall.value, got, r.message)
    for field, want in expected["fields"].items():
        assert got[field] in as_list(want), (field, got[field], want)


VIOLATIONS = [c for c in CASES
              if "fail" in json.loads((FIXTURES / f"{c}.json").read_text())["expected"]["azure_vision"]["overall"]]


@pytest.mark.parametrize("case", VIOLATIONS)
def test_autocorrecting_vision_never_turns_a_violation_into_pass(case):
    """Worst case: the model silently 'fixes' the warning to the standard text and reports the
    standard formatting (heading bold, body regular) whatever the label shows."""
    _, r = run(case, autocorrect=True)
    assert r.overall.value != "pass", [(c.field, c.status.value, c.reason) for c in r.checks]


@pytest.mark.parametrize("case,low,high", [
    ("clean_spirits", 1.4, 3.0), ("warning_heading_not_bold", 0.0, 1.15), ("warning_body_bold", 0.0, 1.15),
])
def test_offline_reader_measures_heading_weight(case, low, high):
    meta = json.loads((FIXTURES / f"{case}.json").read_text())
    from app.core.preprocess import load_image
    r = LocalOcrExtractor().extract(load_image((FIXTURES / meta["image"]).read_bytes()))
    assert r.warning_weight_ratio is not None and low <= r.warning_weight_ratio <= high, r.warning_weight_ratio
