from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("ttb")


class ApiError(Exception):
    def __init__(self, status: int, error_code: str, message: str):
        self.status, self.error_code, self.message = status, error_code, message


def _body(code: str, message: str) -> dict:
    return {"error_code": code, "message": message}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError):
        return JSONResponse(_body(e.error_code, e.message), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, e: RequestValidationError):
        missing = {str(err["loc"][-1]) for err in e.errors()}
        if "image" in missing:
            msg = "Please choose a label image to check."
        elif "application" in missing:
            msg = "The application form data was not sent. Reload the page and try again."
        else:
            msg = "The request was not complete. Reload the page and try again."
        return JSONResponse(_body("invalid_request", msg), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, e: StarletteHTTPException):
        msg = "Page not found." if e.status_code == 404 else "The request could not be completed."
        return JSONResponse(_body(f"http_{e.status_code}", msg), status_code=e.status_code)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, e: Exception):
        # Log the exception type only: never label content or form data.
        log.error("unexpected error: %s", type(e).__name__)
        return JSONResponse(_body("internal_error", "Something went wrong while checking this label. Please try again."),
                            status_code=500)
