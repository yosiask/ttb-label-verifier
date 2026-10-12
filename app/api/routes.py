from __future__ import annotations

import json
import os

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import ValidationError

from ..core.engine import verify
from ..core.extractors.base import ProviderUnavailableError
from ..core.extractors.factory import enabled_providers, get_extractor
from ..core.models import ApplicationData, VerificationResult
from ..core.preprocess import InvalidImageError
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
    return {
        "providers": enabled_providers(),
        "default_provider": os.environ.get("EXTRACTOR", "auto"),
        "max_upload_mb": max_upload_bytes() / 1024 / 1024,
        "allowed_types": sorted(ALLOWED_TYPES),
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


@router.post("/verify", response_model=VerificationResult)
def verify_label(
    image: UploadFile = File(...),
    application: str = Form(...),
    provider: str | None = Form(None),
) -> VerificationResult:
    app_data = _parse_application(application)
    if image.content_type not in ALLOWED_TYPES:
        raise ApiError(415, "bad_file_type", "That file type is not supported. Upload a JPEG, PNG or WebP image of the label.")
    limit = max_upload_bytes()
    data = image.file.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "file_too_large",
                       f"The image is larger than {limit // (1024 * 1024)} MB. Use a smaller photo or lower resolution.")
    if not data:
        raise ApiError(422, "unreadable_image", "The uploaded file is empty. Choose the label image again.")
    try:
        extractor = get_extractor(provider)
        return verify(data, app_data, extractor)
    except InvalidImageError as e:
        raise ApiError(422, "unreadable_image", f"{e} Try saving the label as JPEG or PNG and upload again.")
    except ProviderUnavailableError as e:
        raise ApiError(503, "provider_unavailable", str(e))
