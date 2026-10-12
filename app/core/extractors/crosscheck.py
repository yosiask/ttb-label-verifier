"""Run a primary reader (cloud vision) and offline OCR side by side.

- The OCR reading is attached as `cross_check`, so the engine can catch a vision model
  that "corrects" altered text (e.g. an edited government warning) to the standard wording.
- If the primary fails or times out and fallback is allowed, the OCR reading is used
  instead. OCR has already run in parallel, so falling back costs no extra time.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PIL import Image

from ..models import ExtractedLabel
from .base import LabelExtractor, ProviderUnavailableError

# Shared pool: each request uses two short-lived workers (vision call + OCR).
_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="extract")


class CrossCheckedExtractor:
    def __init__(self, primary: LabelExtractor, secondary: LabelExtractor, allow_fallback: bool):
        self.primary, self.secondary, self.allow_fallback = primary, secondary, allow_fallback
        self.name = primary.name

    def extract(self, image: Image.Image) -> ExtractedLabel:
        # Each reader gets its own copy: PIL images are not safe to share across threads.
        p = _POOL.submit(self.primary.extract, image.copy())
        s = _POOL.submit(self.secondary.extract, image.copy())
        try:
            primary = p.result()
        except ProviderUnavailableError as e:
            if not self.allow_fallback:
                s.cancel()
                raise
            fallback = s.result()  # if offline OCR also fails, that error is the one reported
            return fallback.model_copy(update={
                "fallback_reason": f"{e} Used the offline engine instead.",
            })
        try:
            secondary = s.result()
        except Exception:  # the cross-check is a safeguard, not a requirement
            return primary.model_copy(update={"notes": primary.notes + ["offline cross-check unavailable"]})
        return primary.model_copy(update={"cross_check": secondary})
