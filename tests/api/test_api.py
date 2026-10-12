import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import routes
from app.api.main import app
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
    Image.new("RGB", (40, 40), "white").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def fake(monkeypatch):
    ex = FakeExtractor(make_label())
    monkeypatch.setattr(routes, "get_extractor", lambda provider=None: ex)
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
