"""Application errors and global exception handlers.

Every error response has the same shape, so the frontend needs one error handler:
    {"error": {"code": "not_found", "message": "Invoice not found", "details": null}}

Services raise AppError subclasses (they know nothing about HTTP responses);
the handlers below turn them into JSON responses.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for expected errors. Subclasses set the HTTP status and error code."""

    status_code: int = 500
    code: str = "internal_error"
    message: str = "Something went wrong"

    def __init__(self, message: str | None = None, *, details: Any = None) -> None:
        self.message = message or self.message
        self.details = details
        super().__init__(self.message)


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"
    message = "Bad request"


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Not authenticated"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "forbidden"
    message = "You do not have permission to perform this action"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Resource already exists"


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
        headers=headers,
    )


_HTTP_STATUS_CODES = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        # RFC 7235: a 401 response should tell the client which auth scheme to use.
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return error_response(exc.status_code, exc.code, exc.message, exc.details, headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Simplify Pydantic's error list to field + message (its raw form can contain
        # Python exception objects, which are not JSON-serializable).
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return error_response(422, "validation_error", "Request validation failed", details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Framework-raised errors, e.g. 404 for an unknown URL or 405 for a wrong method.
        code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RateLimitExceeded)
    async def handle_rate_limit(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return error_response(429, "rate_limited", f"Too many requests: limit is {exc.detail}")

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Log the full traceback for us; never leak internals to the client.
        logger.exception("Unhandled error")
        return error_response(500, "internal_error", "Something went wrong")
