"""Picks the extraction provider: local | azure | auto.

local  offline Tesseract only (works inside a firewall)
azure  cloud vision, cross-checked by offline OCR; errors if the cloud is unavailable
auto   cloud vision when configured and allowed, else offline; falls back to offline on cloud failure
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from .base import LabelExtractor, ProviderUnavailableError
from .local_ocr import LocalOcrExtractor, tesseract_available

PROVIDERS = ("local", "azure", "auto")


def azure_configured() -> bool:
    return bool(os.environ.get("AZURE_OPENAI_ENDPOINT") and os.environ.get("AZURE_OPENAI_DEPLOYMENT"))


def crosscheck_enabled() -> bool:
    return os.environ.get("VISION_OCR_CROSSCHECK", "true").lower() not in ("0", "false", "no")


def enabled_providers() -> dict[str, bool]:
    return {"local": tesseract_available(), "azure": azure_configured()}


def default_provider() -> str:
    choice = os.environ.get("EXTRACTOR", "auto").lower()
    return choice if choice in PROVIDERS else "auto"


@lru_cache(maxsize=1)
def _azure(endpoint: str, deployment: str, api_key: str | None, timeout_s: float):
    from .azure_vision import AzureVisionExtractor

    return AzureVisionExtractor(endpoint, deployment, api_key=api_key, timeout_s=timeout_s)


def azure_extractor():
    return _azure(os.environ["AZURE_OPENAI_ENDPOINT"], os.environ["AZURE_OPENAI_DEPLOYMENT"],
                  os.environ.get("AZURE_OPENAI_API_KEY") or None, float(os.environ.get("AZURE_TIMEOUT_S", "8")))


def cloud_cooldown_s() -> float:
    """Seconds left of a cooldown Azure asked for with a 429; 0 when the cloud may be called."""
    if not azure_configured():
        return 0.0
    remaining = getattr(azure_extractor(), "cooldown_remaining", None)
    return remaining() if remaining else 0.0


CAP_REACHED = "Today's cloud AI limit has been reached."
CAP_REACHED_NOTE = "Today's cloud AI limit has been reached, so the offline engine was used."


@dataclass
class Selection:
    extractor: LabelExtractor
    uses_cloud: bool
    note: str | None = None  # shown to the reviewer, e.g. why the offline engine was used


def get_extractor(choice: str | None = None, cloud_allowed: bool = True,
                  blocked_reason: str | None = None) -> Selection:
    """cloud_allowed=False when server-side protection holds the cloud back: the daily cap is
    used up, or the deployment's per-minute budget is spent. blocked_reason says which."""
    choice = (choice or default_provider()).lower()
    if choice not in PROVIDERS:
        raise ProviderUnavailableError(f"Unknown engine \"{choice}\". Use local, azure or auto.")
    local = LocalOcrExtractor()
    if choice == "local":
        return Selection(local, uses_cloud=False)

    if choice == "azure":
        if not azure_configured():
            raise ProviderUnavailableError("The cloud AI engine is not set up on this server. Use the offline engine.")
        if not cloud_allowed:
            raise ProviderUnavailableError(
                f"{blocked_reason or CAP_REACHED} Use the offline engine.")
    elif not azure_configured() or not cloud_allowed:  # auto
        note = None if not azure_configured() else \
            (f"{blocked_reason} The offline engine was used." if blocked_reason else CAP_REACHED_NOTE)
        return Selection(local, uses_cloud=False, note=note)

    from .crosscheck import CrossCheckedExtractor

    allow_fallback = choice == "auto"
    if crosscheck_enabled() or allow_fallback:
        return Selection(CrossCheckedExtractor(azure_extractor(), local, allow_fallback), uses_cloud=True)
    return Selection(azure_extractor(), uses_cloud=True)
