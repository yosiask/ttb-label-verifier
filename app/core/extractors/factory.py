"""Picks the extraction provider: local | azure | auto."""

from __future__ import annotations

import os

from .base import LabelExtractor, ProviderUnavailableError
from .local_ocr import LocalOcrExtractor, tesseract_available

PROVIDERS = ("local", "azure", "auto")


def enabled_providers() -> dict[str, bool]:
    return {"local": tesseract_available(), "azure": False}  # Azure vision arrives in Milestone 2


def get_extractor(choice: str | None = None) -> LabelExtractor:
    choice = (choice or os.environ.get("EXTRACTOR", "auto")).lower()
    if choice not in PROVIDERS:
        raise ProviderUnavailableError(f"Unknown engine \"{choice}\". Use local, azure or auto.")
    if choice == "azure":
        raise ProviderUnavailableError("The cloud AI engine is not configured on this server. Use the offline engine.")
    return LocalOcrExtractor()
