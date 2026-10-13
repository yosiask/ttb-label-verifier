"""FastAPI app: the API under /api and the static single-page UI at /.

Stateless: images and extracted text live in memory for one request only.
Run locally: uvicorn app.api.main:app --port 8710
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import errors
from ..core.engine import MAX_IMAGES
from .protection import BodySizeLimit
from .routes import max_upload_bytes, router

WEB = Path(__file__).resolve().parents[1] / "web"

app = FastAPI(title="TTB Label Verifier", version="0.1.0", docs_url="/api/docs", redoc_url=None)
errors.install(app)
app.include_router(router)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    return response


# Whole-request cap: up to MAX_IMAGES images at the per-image limit, plus 1 MB for the form.
app.add_middleware(BodySizeLimit, max_bytes_fn=lambda: max_upload_bytes() * MAX_IMAGES + 1024 * 1024,
                   shown_mb_fn=lambda: max_upload_bytes() / (1024 * 1024))

app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
