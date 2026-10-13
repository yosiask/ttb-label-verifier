"""Cloud extraction with an Azure OpenAI vision model.

The model only transcribes. It never sees the application data, and it is told not
to correct anything. Deterministic rules decide afterwards.
Auth: managed identity (DefaultAzureCredential); AZURE_OPENAI_API_KEY only for local dev.
"""

from __future__ import annotations

import base64
import io
import json
import os
import threading
import time
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel, ValidationError

from ..models import ExtractedLabel
from .base import ProviderUnavailableError


class ProviderTimeoutError(ProviderUnavailableError):
    """The provider did not answer within its time budget."""


class ProviderRateLimitedError(ProviderUnavailableError):
    """Azure answered 429 (tokens- or requests-per-minute limit). No call is made until the
    cooldown it asked for has passed, so a busy minute falls back to offline OCR at once."""

    def __init__(self, message: str, retry_after_s: float):
        super().__init__(message)
        self.retry_after_s = retry_after_s


MAX_LONG_EDGE = 1600
API_VERSION = "2024-10-21"
# Azure counts max_tokens against the deployment's tokens-per-minute limit on every request,
# whatever the answer's real length, so keep it close to the largest expected reading.
DEFAULT_MAX_OUTPUT_TOKENS = 700  # largest measured reading: 257 tokens (2026-10-13)
COOLDOWN_DEFAULT_S, COOLDOWN_MIN_S, COOLDOWN_MAX_S = 5.0, 1.0, 60.0
RATE_LIMITED_MESSAGE = "The cloud AI engine is at its usage limit right now."

SYSTEM_PROMPT = """You transcribe alcohol beverage labels for a compliance reviewer.
Report exactly what is printed. Do not correct spelling, capitalization, punctuation or wording,
even when you recognize standard text such as the government health warning: if the label says
something different from the standard wording, transcribe what the label says.
Do not guess text you cannot read: write [illegible] in place of any word you cannot read,
and use null for a field that is not present or not legible at all.
You are not told what the label should say, and you must not judge compliance."""

USER_PROMPT = """Transcribe this label.
- full_text: every line of text on the label except the government warning statement, top to bottom,
  one printed line per line, exactly as printed (the warning goes only in warning_text).
- brand_name, class_type (e.g. "Kentucky Straight Bourbon Whiskey"), alcohol_content (the full statement,
  e.g. "45% Alc./Vol. (90 Proof)"), net_contents, producer_name_address (the full "bottled by ..." statement),
  country_of_origin (the full statement, e.g. "Product of Scotland"): exactly as printed, or null.
- warning_text: the government health warning statement, verbatim, character for character, including
  its heading exactly as capitalized and punctuated on the label; null if there is none.
- warning_heading_bold: is the heading "GOVERNMENT WARNING" (or however it is printed) in bold type?
- warning_body_bold: is the rest of the warning statement after the heading in bold type?
  Use null for either if you cannot tell.
- legibility: "clear", "partly_legible" (some text hard to read: glare, blur, angle) or "illegible".
- legibility_note: one short sentence on what made the label hard to read, or null."""

_NULLABLE_STR = {"type": ["string", "null"]}
_NULLABLE_BOOL = {"type": ["boolean", "null"]}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "full_text": {"type": "string"},
        "brand_name": _NULLABLE_STR,
        "class_type": _NULLABLE_STR,
        "alcohol_content": _NULLABLE_STR,
        "net_contents": _NULLABLE_STR,
        "producer_name_address": _NULLABLE_STR,
        "country_of_origin": _NULLABLE_STR,
        "warning_text": _NULLABLE_STR,
        "warning_heading_bold": _NULLABLE_BOOL,
        "warning_body_bold": _NULLABLE_BOOL,
        "legibility": {"type": "string", "enum": ["clear", "partly_legible", "illegible"]},
        "legibility_note": _NULLABLE_STR,
    },
}
SCHEMA["required"] = list(SCHEMA["properties"])

LEGIBILITY_CONFIDENCE = {"clear": 0.95, "partly_legible": 0.65, "illegible": 0.2}
FIELD_KEYS = ("brand_name", "class_type", "alcohol_content", "net_contents", "producer_name_address", "country_of_origin")


class VisionReading(BaseModel):
    full_text: str
    brand_name: str | None
    class_type: str | None
    alcohol_content: str | None
    net_contents: str | None
    producer_name_address: str | None
    country_of_origin: str | None
    warning_text: str | None
    warning_heading_bold: bool | None
    warning_body_bold: bool | None
    legibility: Literal["clear", "partly_legible", "illegible"]
    legibility_note: str | None


def encode_image(image: Image.Image, max_long_edge: int = MAX_LONG_EDGE) -> str:
    img = image.convert("RGB")
    long_edge = max(img.size)
    if long_edge > max_long_edge:
        s = max_long_edge / long_edge
        img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def build_client(endpoint: str, api_key: str | None = None):
    from openai import AzureOpenAI

    if api_key:
        return AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=API_VERSION, max_retries=0)
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    token_provider = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
    return AzureOpenAI(azure_endpoint=endpoint, azure_ad_token_provider=token_provider,
                       api_version=API_VERSION, max_retries=0)


def _empty_none(v: str | None) -> str | None:
    return v if v and v.strip() else None


def retry_after_seconds(error: Exception) -> float:
    """Wait asked for by a 429 (retry-after-ms, else retry-after), clamped to a sane range."""
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    wait = None
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        try:
            wait = float(headers.get(name)) * scale
            break
        except (TypeError, ValueError):
            continue
    if wait is None:
        wait = COOLDOWN_DEFAULT_S
    return min(COOLDOWN_MAX_S, max(COOLDOWN_MIN_S, wait))


class AzureVisionExtractor:
    name = "azure_vision"

    def __init__(self, endpoint: str, deployment: str, api_key: str | None = None,
                 timeout_s: float = 8.0, client: Any = None, max_output_tokens: int | None = None):
        self.deployment = deployment
        self.timeout_s = timeout_s
        self.max_output_tokens = max_output_tokens or int(
            os.environ.get("AZURE_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS))
        self._client = client
        self._endpoint, self._api_key = endpoint, api_key
        self._cooldown_until = 0.0
        self._lock = threading.Lock()

    def cooldown_remaining(self) -> float:
        """Seconds until the cloud may be called again after a 429; 0 when it is free."""
        with self._lock:
            return max(0.0, self._cooldown_until - time.monotonic())

    def _start_cooldown(self, seconds: float) -> None:
        with self._lock:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)

    @property
    def client(self):
        if self._client is None:
            self._client = build_client(self._endpoint, self._api_key)
        return self._client

    def extract(self, image: Image.Image) -> ExtractedLabel:
        import openai

        wait = self.cooldown_remaining()
        if wait:
            raise ProviderRateLimitedError(RATE_LIMITED_MESSAGE, wait)
        t0 = time.perf_counter()
        data_url = encode_image(image)
        t1 = time.perf_counter()
        try:
            raw = self.client.chat.completions.with_raw_response.create(
                model=self.deployment,
                temperature=0,
                max_tokens=self.max_output_tokens,
                timeout=self.timeout_s,
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "label_reading", "strict": True, "schema": SCHEMA}},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": [
                        {"type": "text", "text": USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                    ]},
                ],
            )
            resp = raw.parse()
            limit_headers = {k: raw.headers.get(h) for k, h in (
                ("ratelimit_remaining_tokens", "x-ratelimit-remaining-tokens"),
                ("ratelimit_remaining_requests", "x-ratelimit-remaining-requests"))}
        except openai.APITimeoutError as e:
            raise ProviderTimeoutError(f"The cloud AI engine did not answer within {self.timeout_s:g} seconds.") from e
        except openai.RateLimitError as e:
            wait = retry_after_seconds(e)
            self._start_cooldown(wait)
            raise ProviderRateLimitedError(RATE_LIMITED_MESSAGE, wait) from e
        except openai.OpenAIError as e:
            raise ProviderUnavailableError(f"The cloud AI engine could not be reached ({type(e).__name__}).") from e
        t2 = time.perf_counter()

        try:
            choice = resp.choices[0]
            if getattr(choice, "finish_reason", None) not in (None, "stop"):
                raise ValueError(f"finish_reason={choice.finish_reason}")
            reading = VisionReading.model_validate(json.loads(choice.message.content))
        except (ValueError, ValidationError, TypeError, IndexError, AttributeError) as e:
            raise ProviderUnavailableError("The cloud AI engine returned an answer that could not be used.") from e

        usage = getattr(resp, "usage", None)
        token_usage = {k: int(getattr(usage, k)) for k in ("prompt_tokens", "completion_tokens")
                       if isinstance(getattr(usage, k, None), int)} if usage else {}
        # Azure's own count against the per-minute quota, to calibrate CLOUD_REQUESTS_PER_MINUTE.
        token_usage.update({k: int(v) for k, v in limit_headers.items() if v and str(v).isdigit()})
        notes = []
        if reading.legibility != "clear" and reading.legibility_note:
            notes.append(reading.legibility_note.strip().rstrip("."))
        return ExtractedLabel(
            provider="azure_vision",
            full_text=reading.full_text,
            fields={k: _empty_none(getattr(reading, k)) for k in FIELD_KEYS},
            warning_text=_empty_none(reading.warning_text),
            warning_heading_bold=reading.warning_heading_bold,
            warning_body_bold=reading.warning_body_bold,
            confidence=LEGIBILITY_CONFIDENCE[reading.legibility],
            word_confidences=[],
            extraction_ms=int((t2 - t1) * 1000),
            preprocess_ms=int((t1 - t0) * 1000),
            notes=notes,
            token_usage=token_usage or None,
        )
