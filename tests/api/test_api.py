import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import protection, routes
from app.api.main import app
from app.core.extractors.factory import Selection
from tests.conftest import FakeExtractor, make_label

client = TestClient(app)

APP = {
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
    "producer_name_address": "Old Tom Distillery, Bardstown, Kentucky",
}


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), "white").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch):
    for k in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT", "EXTRACTOR"):
        monkeypatch.delenv(k, raising=False)
    protection.reset_for_tests()
    yield
    protection.reset_for_tests()


@pytest.fixture
def fake(monkeypatch):
    ex = FakeExtractor(make_label())
    monkeypatch.setattr(routes, "get_extractor", lambda choice=None, cloud_allowed=True: Selection(ex, False))
    return ex


def post(image=None, application=APP, ctype="image/png", provider=None):
    files = {"image": ("label.png", image if image is not None else png(), ctype)}
    data = {"application": application if isinstance(application, str) else json.dumps(application)}
    if provider:
        data["provider"] = provider
    return client.post("/api/verify", files=files, data=data)


def test_health_and_config():
    assert client.get("/api/health").json() == {"status": "ok"}
    cfg = client.get("/api/config").json()
    assert cfg["max_upload_mb"] == 10 and "local" in cfg["providers"]


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200 and "Verify label" in r.text


def test_verify_ok(fake):
    r = post()
    assert r.status_code == 200
    body = r.json()
    assert body["overall"] == "needs_review"
    assert body["timings_ms"]["total"] >= 0
    assert r.headers["cache-control"] == "no-store"


def test_bad_file_type(fake):
    r = post(image=b"%PDF-1.4", ctype="application/pdf")
    assert r.status_code == 415 and r.json()["error_code"] == "bad_file_type"


def test_too_large(fake, monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "0.001")
    r = post(image=b"x" * 5000)
    assert r.status_code == 413 and r.json()["error_code"] == "file_too_large"


def test_corrupt_image(fake):
    r = post(image=b"not really a png")
    assert r.status_code == 422 and r.json()["error_code"] == "unreadable_image"
    assert "Traceback" not in r.text


def test_missing_fields_named_in_plain_english(fake):
    r = post(application={**APP, "brand_name": "  ", "net_contents": ""})
    assert r.status_code == 422
    assert r.json()["message"] == "Please fill in: Brand name, Net contents."


def test_bad_json(fake):
    r = post(application="{not json")
    assert r.status_code == 422 and r.json()["error_code"] == "invalid_application"


def test_missing_image():
    r = client.post("/api/verify", data={"application": json.dumps(APP)})
    assert r.status_code == 422 and "label image" in r.json()["message"]


def test_cloud_provider_unavailable():
    r = post(provider="azure")
    assert r.status_code == 503 and r.json()["error_code"] == "provider_unavailable"


def test_unknown_route_is_plain_json():
    r = client.get("/api/nope")
    assert r.status_code == 404 and r.json()["error_code"] == "http_404"


# --- Server-side usage protection ---

def test_rate_limit_per_ip(fake, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    protection.reset_for_tests()
    assert post().status_code == 200
    assert post().status_code == 200
    r = post()
    assert r.status_code == 429 and r.json()["error_code"] == "rate_limited"
    assert int(r.headers["retry-after"]) >= 1
    assert "Wait about" in r.json()["message"]


def test_rate_limiter_window_slides():
    rl = protection.RateLimiter(2, window_s=60)
    assert rl.check("a", now=0) == 0 and rl.check("a", now=1) == 0
    assert rl.check("a", now=2) > 0
    assert rl.check("b", now=2) == 0  # other clients unaffected
    assert rl.check("a", now=61) == 0  # first hit expired


def test_client_ip_uses_only_trusted_proxy_entry(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    p = protection.reset_for_tests()

    class Req:
        headers = {"x-forwarded-for": "6.6.6.6, 203.0.113.9"}  # first entry is client-supplied
        client = type("C", (), {"host": "10.0.0.1"})()
    assert p.client_ip(Req()) == "203.0.113.9"
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "0")
    assert protection.reset_for_tests().client_ip(Req()) == "10.0.0.1"


def test_oversized_body_rejected_before_parsing(monkeypatch):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    called = []
    monkeypatch.setattr(routes, "get_extractor", lambda *a, **k: called.append(1))
    r = post(image=b"x" * (3 * 1024 * 1024))
    assert r.status_code == 413 and r.json()["error_code"] == "file_too_large"
    assert not called


def test_busy_server_returns_plain_503(fake, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_VERIFICATIONS", "1")
    monkeypatch.setenv("QUEUE_WAIT_S", "0")
    p = protection.reset_for_tests()
    p.concurrency.acquire()
    try:
        r = post()
    finally:
        p.concurrency.release()
    assert r.status_code == 503 and r.json()["error_code"] == "busy"


def test_daily_cap_counts_and_resets():
    cap = protection.DailyCap(2)
    assert cap.try_take() and cap.try_take() and not cap.try_take()
    assert cap.remaining() == 0
    cap._day = None  # simulate a new UTC day
    assert cap.try_take()


class CloudFake(FakeExtractor):
    name = "azure_vision"


def test_auto_uses_cloud_until_daily_cap_then_offline(monkeypatch):
    from app.core.extractors import factory

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.invalid/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "vision")
    monkeypatch.setenv("CLOUD_DAILY_CAP", "1")
    protection.reset_for_tests()
    cloud = CloudFake(make_label(provider="azure_vision", heading_bold=True, body_bold=False))
    local = FakeExtractor(make_label())
    monkeypatch.setattr(factory, "azure_extractor", lambda: cloud)
    monkeypatch.setattr(factory, "LocalOcrExtractor", lambda: local)

    first = post(provider="auto").json()
    assert first["provider"] == "azure_vision" and first["overall"] == "pass"
    second = post(provider="auto").json()
    assert second["provider"] == "local_ocr"
    assert "cloud AI limit" in second["message"]
    assert cloud.seen_images == 1
    r = post(provider="azure")
    assert r.status_code == 503 and "limit" in r.json()["message"]
    assert client.get("/api/config").json()["cloud_available_today"] is False


def test_local_choice_never_counts_against_cloud_cap(monkeypatch):
    from app.core.extractors import factory

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.invalid/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "vision")
    p = protection.reset_for_tests()
    monkeypatch.setattr(factory, "LocalOcrExtractor", lambda: FakeExtractor(make_label()))
    before = p.cloud_cap.remaining()
    assert post(provider="local").status_code == 200
    assert p.cloud_cap.remaining() == before
