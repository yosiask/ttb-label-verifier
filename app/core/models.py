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
    warning_text: str | None
    warning_heading_bold: bool | None  # None = could not determine
    warning_body_bold: bool | None
    confidence: float  # 0..1 overall readability
    word_confidences: list[tuple[str, float]] = []  # OCR only, reading order, 0..100
    extraction_ms: int
    preprocess_ms: int = 0
    notes: list[str] = []  # provider remarks shown to the reviewer (e.g. "deskewed 4.5 degrees")


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
    timings_ms: dict[str, int]
