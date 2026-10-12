"""Azure vision provider against a fake client: no network, no cost."""

import base64
import io
import json
from types import SimpleNamespace

import httpx
import openai
import pytest
from PIL import Image

from app.core.extractors.azure_vision import SCHEMA, AzureVisionExtractor, ProviderTimeoutError
from app.core.extractors.base import ProviderUnavailableError
from app.core.warning import CANONICAL_WARNING

READING = {
    "full_text": "OLD TOM DISTILLERY\nKentucky Straight Bourbon Whiskey\n45% Alc./Vol. (90 Proof)\n750 mL",
    "brand_name": "OLD TOM DISTILLERY", "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)", "net_contents": "750 mL",
    "producer_name_address": "Distilled and Bottled by Old Tom Distillery, Bardstown, Kentucky",
    "country_of_origin": None, "warning_text": CANONICAL_WARNING,
    "warning_heading_bold": True, "warning_body_bold": False,
    "legibility": "clear", "legibility_note": None,
}


class FakeCompletions:
    def __init__(self, content=None, error=None, finish_reason="stop"):
        self.content, self.error, self.finish_reason = content, error, finish_reason
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        msg = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=self.finish_reason)])


def extractor(**kw):
    comp = FakeCompletions(**kw)
    client = SimpleNamespace(chat=SimpleNamespace(completions=comp))
    return AzureVisionExtractor("https://example.invalid/", "vision-dep", client=client), comp


def img(w=3000, h=2000):
    return Image.new("RGB", (w, h), "white")


def test_reading_mapped_to_extracted_label():
    ex, comp = extractor(content=json.dumps(READING))
    r = ex.extract(img())
    assert r.provider == "azure_vision"
    assert r.fields["brand_name"] == "OLD TOM DISTILLERY" and r.fields["country_of_origin"] is None
    assert r.warning_text == CANONICAL_WARNING
    assert r.warning_heading_bold is True and r.warning_body_bold is False
    assert r.confidence >= 0.9 and r.word_confidences == []


def test_request_is_deterministic_structured_and_time_capped():
    ex, comp = extractor(content=json.dumps(READING))
    ex.extract(img())
    call = comp.calls[0]
    assert call["temperature"] == 0
    assert call["timeout"] == 8.0
    assert call["model"] == "vision-dep"
    rf = call["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True


def test_image_downscaled_to_1600_jpeg():
    ex, comp = extractor(content=json.dumps(READING))
    ex.extract(img(3200, 2400))
    url = comp.calls[0]["messages"][1]["content"][1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    sent = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(sent.size) == 1600


def test_extraction_is_blind():
    """Only fixed instructions and the image are sent: never application data."""
    ex, comp = extractor(content=json.dumps(READING))
    ex.extract(img())
    msgs = comp.calls[0]["messages"]
    texts = [msgs[0]["content"], msgs[1]["content"][0]["text"]]
    from app.core.extractors.azure_vision import SYSTEM_PROMPT, USER_PROMPT
    assert texts == [SYSTEM_PROMPT, USER_PROMPT]
    assert "do not correct" in SYSTEM_PROMPT.lower()


def test_schema_is_strict_compatible():
    assert SCHEMA["additionalProperties"] is False
    assert set(SCHEMA["required"]) == set(SCHEMA["properties"])


def test_legibility_maps_to_confidence_and_note():
    ex, _ = extractor(content=json.dumps({**READING, "legibility": "illegible", "legibility_note": "Strong glare."}))
    r = ex.extract(img())
    assert r.confidence < 0.55 and r.notes == ["Strong glare"]


def test_empty_strings_become_none():
    ex, _ = extractor(content=json.dumps({**READING, "warning_text": "  ", "brand_name": ""}))
    r = ex.extract(img())
    assert r.warning_text is None and r.fields["brand_name"] is None


def test_timeout_raises_provider_timeout():
    req = httpx.Request("POST", "https://example.invalid/")
    ex, _ = extractor(error=openai.APITimeoutError(request=req))
    with pytest.raises(ProviderTimeoutError):
        ex.extract(img())


@pytest.mark.parametrize("kw", [
    {"content": "not json"},
    {"content": json.dumps({"full_text": "x"})},
    {"content": json.dumps(READING), "finish_reason": "length"},
    {"content": json.dumps(READING), "finish_reason": "content_filter"},
])
def test_unusable_answers_raise_unavailable(kw):
    ex, _ = extractor(**kw)
    with pytest.raises(ProviderUnavailableError):
        ex.extract(img())


def test_connection_error_is_unavailable():
    req = httpx.Request("POST", "https://example.invalid/")
    ex, _ = extractor(error=openai.APIConnectionError(request=req))
    with pytest.raises(ProviderUnavailableError, match="could not be reached"):
        ex.extract(img())
