"""Typed application errors and FastAPI exception handlers.

Every error returned by the API uses the same envelope:

    {
      "error": {
        "code": "string",
        "message": "string",
        "correlation_id": "uuid|null",
        "details": { ... } | null
      }
    }

Codes are stable strings that clients and operators can match on. HTTP
statuses are derived from the exception class. Validation and unhandled
exceptions get sane fallbacks; nothing leaks stack traces to the response.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from wabot.infra.correlation import get_current_correlation_id
from wabot.infra.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Envelope models (used for OpenAPI documentation as well)
# ---------------------------------------------------------------------------


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    correlation_id: str | None = None
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorEnvelope


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class WabotError(Exception):
    """Base class for application-level errors with stable codes."""

    code: str = "internal_error"
    http_status: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    message: str = "An internal error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message or self.message)
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.details = details


class ValidationFailedError(WabotError):
    code = "validation_failed"
    http_status = status.HTTP_400_BAD_REQUEST
    message = "Request validation failed."


class NotFoundError(WabotError):
    code = "not_found"
    http_status = status.HTTP_404_NOT_FOUND
    message = "Resource not found."


class ConflictError(WabotError):
    code = "conflict"
    http_status = status.HTTP_409_CONFLICT
    message = "Conflicting request."


class DependencyUnavailableError(WabotError):
    code = "dependency_unavailable"
    http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    message = "A required dependency is unavailable."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope_response(
    *,
    code: str,
    message: str,
    http_status: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorEnvelope(
            code=code,
            message=message,
            correlation_id=get_current_correlation_id(),
            details=details,
        )
    )
    return JSONResponse(status_code=http_status, content=jsonable_encoder(body))


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def _handle_wabot_error(_: Request, exc: Exception) -> JSONResponse:
    exc = cast("WabotError", exc)
    logger.warning(
        "wabot.error",
        code=exc.code,
        http_status=exc.http_status,
        message=exc.message,
        details=exc.details,
    )
    return _envelope_response(
        code=exc.code,
        message=exc.message,
        http_status=exc.http_status,
        details=exc.details,
    )


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    exc = cast("StarletteHTTPException", exc)
    code_map = {
        status.HTTP_400_BAD_REQUEST: "bad_request",
        status.HTTP_401_UNAUTHORIZED: "unauthorized",
        status.HTTP_403_FORBIDDEN: "forbidden",
        status.HTTP_404_NOT_FOUND: "not_found",
        status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
        status.HTTP_409_CONFLICT: "conflict",
        status.HTTP_413_CONTENT_TOO_LARGE: "payload_too_large",
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
        status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_failed",
        status.HTTP_429_TOO_MANY_REQUESTS: "rate_limited",
    }
    code = code_map.get(exc.status_code, f"http_{exc.status_code}")
    detail = exc.detail if isinstance(exc.detail, str) else None
    details = exc.detail if not isinstance(exc.detail, str) else None
    logger.info("wabot.http_error", code=code, http_status=exc.status_code, detail=detail)
    return _envelope_response(
        code=code,
        message=detail or code.replace("_", " ").capitalize(),
        http_status=exc.status_code,
        details={"detail": details} if details is not None else None,
    )


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    exc = cast("RequestValidationError", exc)
    logger.info("wabot.validation_error", error_count=len(exc.errors()))
    return _envelope_response(
        code="validation_failed",
        message="Request validation failed.",
        http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
        details={"errors": jsonable_encoder(exc.errors())},
    )


async def _handle_unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("wabot.unhandled_exception", exc_type=type(exc).__name__)
    return _envelope_response(
        code="internal_error",
        message="An internal error occurred.",
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(WabotError, _handle_wabot_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unhandled_error)
