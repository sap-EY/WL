"""Correlation-id propagation.

Every inbound HTTP request gets a correlation id:
- pulled from the `X-Correlation-Id` header if the client supplied one, or
- freshly generated as a UUIDv4 otherwise.

The id is:
1. stored on `request.state.correlation_id` for handlers and exception
   handlers to read,
2. bound into structlog contextvars so every log line in this request task
   carries `correlation_id`, `method`, `path`,
3. echoed back on the response as `X-Correlation-Id`.

A later phase will copy the same id into outbound queue message headers and
into Interakt outbound `callbackData` (see implementation_plan.md §7.8).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

CORRELATION_HEADER = "X-Correlation-Id"


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def get_current_correlation_id() -> str | None:
    """Read the correlation id bound to the current async task, if any."""
    value = structlog.contextvars.get_contextvars().get("correlation_id")
    return value if isinstance(value, str) else None


class CorrelationMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that binds correlation context for the request lifetime."""

    def __init__(self, app: ASGIApp, header_name: str = CORRELATION_HEADER) -> None:
        super().__init__(app)
        self._header_name = header_name

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(self._header_name)
        correlation_id = incoming.strip() if incoming else new_correlation_id()
        request.state.correlation_id = correlation_id

        # Bind for this task only; clear after to avoid leakage across requests
        # served by the same worker task pool.
        token = structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            method=request.method,
            path=request.url.path,
        )
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.reset_contextvars(**token)

        response.headers[self._header_name] = correlation_id
        return response
