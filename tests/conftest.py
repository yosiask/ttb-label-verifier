from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw

from app.core.models import ApplicationData, ExtractedLabel
from app.core.warning import CANONICAL_WARNING

LABEL_TEXT = """OLD TOM DISTILLERY
Kentucky Straight Bourbon Whiskey
45% Alc./Vol. (90 Proof)
750 mL
Distilled and Bottled by Old Tom Distillery, Bardstown, Kentucky"""


def make_label(text: str = LABEL_TEXT, warning: str | None = CANONICAL_WARNING, confidence: float = 0.92,
               heading_bold: bool | None = None, body_bold: bool | None = None,
               word_confidences: list[tuple[str, float]] | None = None, **kw) -> ExtractedLabel:
    full = text + ("\n" + warning if warning else "")
    if word_confidences is None:
        word_confidences = [(w, 95.0) for w in full.split()]
    return ExtractedLabel(provider=kw.pop("provider", "local_ocr"), full_text=full, warning_text=warning,
                          warning_heading_bold=heading_bold, warning_body_bold=body_bold,
                          confidence=confidence, word_confidences=word_confidences, extraction_ms=1, **kw)


@pytest.fixture
def application() -> ApplicationData:
    return ApplicationData(
        brand_name="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        alcohol_content="45% Alc./Vol. (90 Proof)",
        net_contents="750 mL",
        producer_name_address="Old Tom Distillery, Bardstown, Kentucky",
    )


class FakeExtractor:
    """Returns a fixed ExtractedLabel; lets engine and API tests run without Tesseract."""

    name = "fake"

    def __init__(self, label: ExtractedLabel):
        self.label = label
        self.seen_images = 0

    def extract(self, image):
        self.seen_images += 1
        return self.label


def text_png(color="white", size=(800, 600)) -> bytes:
    """A small image with lines of dark text, so image-quality checks see a sharp photo."""
    img = Image.new("RGB", size, color)
    d = ImageDraw.Draw(img)
    for y in range(30, size[1] - 30, 24):
        d.text((20, y), "GOVERNMENT WARNING: (1) According to the Surgeon General", fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
