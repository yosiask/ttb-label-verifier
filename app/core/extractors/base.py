from __future__ import annotations

from typing import Protocol

from PIL import Image

from ..models import ExtractedLabel


class ProviderUnavailableError(RuntimeError):
    """The requested extraction provider is not configured or not reachable."""


class LabelExtractor(Protocol):
    """Reads a label image. Blind by design: never receives the application data,
    so it cannot be biased toward reporting the expected answer."""

    name: str

    def extract(self, image: Image.Image) -> ExtractedLabel: ...
