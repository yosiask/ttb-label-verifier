from __future__ import annotations

import json
import os

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import ValidationError

from ..core.engine import MAX_IMAGES, verify
from ..core.extractors.base import ProviderUnavailableError
from ..core.extractors.factory import (azure_configured, cloud_cooldown_s, default_provider, enabled_providers,
                                      get_extractor)
from ..core.models import ApplicationData, VerificationResult
from ..core.preprocess import InvalidImageError
from . import protection
from .errors import ApiError

router = APIRouter(prefix="/api")

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
FIELD_NAMES = {
    "brand_name": "Brand name", "class_type": "Class/type", "alcohol_content": "Alcohol content",
    "net_contents": "Net contents", "producer_name_address": "Producer name and address",
    "country_of_origin": "Country of origin", "is_import": "Imported?", "beverage_type": "Beverage type",
}


def max_upload_bytes() -> int:
    return int(float(os.environ.get("MAX_UPLOAD_MB", "10")) * 1024 * 1024)


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/config")
def config() -> dict:
    p = protection.PROTECTION
    return {
        "providers": enabled_providers(),
        "default_provider": default_provider(),
        "cloud_available_today": azure_configured() and p.cloud_cap.remaining() > 0,
        "max_upload_mb": max_upload_bytes() / 1024 / 1024,
        "allowed_types": sorted(ALLOWED_TYPES),
        "rate_limit_per_minute": p.rate.per_minute,
    }


def _parse_application(raw: str) -> ApplicationData:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ApiError(422, "invalid_application", "The application data could not be read. Reload the page and try again.")
    try:
        return ApplicationData.model_validate(data)
    except ValidationError as e:
        missing = sorted({FIELD_NAMES.get(str(err["loc"][0]), str(err["loc"][0])) for err in e.errors() if err["loc"]})
        raise ApiError(422, "invalid_application",
                       "Please fill in: " + ", ".join(missing) + "." if missing else "Some form fields are not valid.")


def _form_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@router.post("/verify", response_model=VerificationResult)
def verify_label(
    request: Request,
    image: list[UploadFile] = File(...),
    application: str = Form(...),
    provider: str | None = Form(None),
    all_sides: str | None = Form(None),
    wait_for_cloud: str | None = Form(None),
) -> VerificationResult:
    """One label: one or more images of it (front, back, ...; repeat the `image` field).
    all_sides=true says the images show every side, so anything not found is missing (Fail);
    otherwise absences are Needs review. wait_for_cloud=true (batch runs): when the cloud is
    busy, wait up to CLOUD_WAIT_S for it instead of using offline OCR at once."""
    p = protection.PROTECTION
    wait = p.rate.check(p.client_ip(request))
    if wait:
        raise ApiError(429, "rate_limited",
                       f"Too many checks from this connection in the last minute. Wait about {wait:.0f} seconds and try again.",
                       headers={"Retry-After": str(int(wait) + 1)})

    app_data = _parse_application(application)
    if len(image) > MAX_IMAGES:
        raise ApiError(422, "too_many_images",
                       f"Upload at most {MAX_IMAGES} images of one label (for example front, back and neck).")
    limit = max_upload_bytes()
    datas = []
    for upload in image:
        if upload.content_type not in ALLOWED_TYPES:
            raise ApiError(415, "bad_file_type",
                           "That file type is not supported. Upload a JPEG, PNG or WebP image of the label.")
        data = upload.file.read(limit + 1)
        if len(data) > limit:
            raise ApiError(413, "file_too_large",
                           f"The image is larger than {limit // (1024 * 1024)} MB. Use a smaller photo or lower resolution.")
        if not data:
            raise ApiError(422, "unreadable_image", "The uploaded file is empty. Choose the label image again.")
        datas.append(data)

    choice = (provider or default_provider()).lower()
    blocked = None
    if choice in ("azure", "auto") and azure_configured():
        # Decided before taking a processing slot, so a batch waiting for the cloud does not
        # hold up other requests.
        blocked = p.wait_for_cloud(cloud_cooldown_s, len(datas), p.cloud_wait_s if _form_bool(wait_for_cloud) else 0)
    if not p.concurrency.acquire(timeout=p.queue_wait_s):
        raise ApiError(503, "busy", "The server is busy checking other labels. Please try again in a moment.",
                       headers={"Retry-After": "10"})
    try:
        selection = get_extractor(choice, cloud_allowed=blocked is None, blocked_reason=blocked)
        result = verify(datas, app_data, selection.extractor, all_sides=_form_bool(all_sides))
    except InvalidImageError as e:
        which = " One of the images:" if len(datas) > 1 else ""
        raise ApiError(422, "unreadable_image", f"{which} {e} Try saving the label as JPEG or PNG and upload again.".strip())
    except ProviderUnavailableError as e:
        raise ApiError(503, "provider_unavailable", str(e))
    finally:
        p.concurrency.release()
    if selection.note:
        result.message = f"{selection.note} {result.message or ''}".strip()
    return result
