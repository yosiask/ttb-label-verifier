"""Typed contracts shared by the engine, the extractors and any front end."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Status(str, Enum):
    PASS = "pass"
    NEEDS_REVIEW = "needs_review"
    FAIL = "fail"
    NOT_APPLICABLE = "n/a"


class ApplicationData(BaseModel):
    """What the applicant claims. Entered by the reviewer from the application."""

    brand_name: str = Field(min_length=1, max_length=200)
    class_type: str = Field(min_length=1, max_length=200)
    alcohol_content: str = Field(min_length=1, max_length=100)
    net_contents: str = Field(min_length=1, max_length=100)
    producer_name_address: str = Field(min_length=1, max_length=400)
    country_of_origin: str | None = Field(default=None, max_length=100)
    is_import: bool = False
    beverage_type: Literal["spirits", "wine", "beer"] = "spirits"

    @field_validator("brand_name", "class_type", "alcohol_content", "net_contents", "producer_name_address")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()

    @field_validator("country_of_origin")
    @classmethod
    def _blank_to_none(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return v.strip()


class ExtractedLabel(BaseModel):
    """What a provider read from the label. Providers never see ApplicationData."""

    provider: Literal["local_ocr", "azure_vision"]
    full_text: str  # all text read, reading order, one physical line per "\n"
    fields: dict[str, str | None] = {}  # provider's best guess per field (OCR leaves these empty)
    # Several images: what the other panels read for a field, when it differs from `fields` (merge only).
    field_alternatives: dict[str, list[str]] = {}
    warning_text: str | None
    warning_heading_bold: bool | None  # None = could not determine
    warning_body_bold: bool | None
    confidence: float  # 0..1 overall readability
    word_confidences: list[tuple[str, float]] = []  # OCR only, reading order, 0..100
    extraction_ms: int
    preprocess_ms: int = 0
    notes: list[str] = []  # provider remarks shown to the reviewer (e.g. "deskewed 4.5 degrees")
    # A second, independent reading (offline OCR alongside cloud vision). Used only to catch
    # disagreements, e.g. a vision model "correcting" an altered warning to the standard text.
    cross_check: ExtractedLabel | None = None
    fallback_reason: str | None = None  # set when this reading replaced a provider that failed
    # Offline OCR only: warning heading stroke / body stroke measured from pixels (see stroke.py).
    # About 1.8 for a bold heading over a regular body; about 1.0 when both have the same weight.
    warning_weight_ratio: float | None = None
    # Offline OCR only: lines holding class/type words, re-read close up from unenhanced pixels.
    # Readers normalize misspellings toward familiar words ("BOUBON" read as "BOURBON"); a second,
    # magnified reading sometimes keeps the letters as printed.
    closeup_lines: list[str] = []
    # Cloud only: tokens billed for the call, e.g. {"prompt_tokens": 2900, "completion_tokens": 410}.
    token_usage: dict[str, int] | None = None


class ImageQuality(BaseModel):
    width: int
    height: int
    sharpness: float  # Laplacian variance / gray variance at a standard size; low = blurry
    brightness: float  # mean gray level 0..255
    contrast: float  # gray-level standard deviation
    issues: list[str] = []  # plain-English problems, e.g. "The photo is blurry."


class FieldCheck(BaseModel):
    field: str
    status: Status
    expected: str | None
    found: str | None
    rule: str
    reason: str
    details: dict[str, Any] = {}


class VerificationResult(BaseModel):
    overall: Status
    checks: list[FieldCheck]
    not_checked: list[str]
    image_readable: bool
    provider: str
    message: str | None = None  # banner-level explanation, e.g. "request a better image"
    image_quality: ImageQuality | None = None  # of the hardest-to-read image when there are several
    image_count: int = 1
    all_sides: bool = True  # False: the images may not show every side, so absences are Needs review
    timings_ms: dict[str, int]
    # Tokens billed for the cloud call, for cost tracking; None when the cloud was not used.
    token_usage: dict[str, int] | None = None
