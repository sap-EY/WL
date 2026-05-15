"""Async HTTP client for Interakt's outbound message API.

Wraps `POST {INTERAKT_BASE_URL}/v1/public/message/`. The client has
**no awareness** of `outbound_message` rows or journey state \u2014 those
live in `services.outbound_pipeline`. This module is a focused
adapter:

* Serialise an `OutboundIntent` (+ `callbackData`) to the right
  Interakt wire shape (`Text`, `InteractiveButton`, or `Template`).
* Send it with the project-wide retry policy (network / 5xx / 429
  retried via `tenacity`; 4xx surfaced as `InteraktPermanentError`).

We do NOT cap RPS on our side. Interakt enforces its own rate limit
and signals via HTTP 429 \u2014 the retry loop handles backoff when that
happens.

Auth: `Authorization: Basic {INTERAKT_API_KEY}` exactly as documented
\u2014 we do NOT base64-encode the configured key (Interakt issues an
already-encoded value; passing it through is the documented contract).
"""

from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from wabot.infra.logging import get_logger

try:
    import truststore
except ImportError:  # pragma: no cover - truststore is a hard dep
    truststore = None

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from wabot.domain.outbound import OutboundIntent
    from wabot.infra.config import AppSettings

logger = get_logger(__name__)

_INTERAKT_SEND_PATH = "/v1/public/message/"
_HTTP_BAD_REQUEST = 400
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR = 500
_HTTP_LIMIT = 600


class InteraktError(RuntimeError):
    """Base class for Interakt adapter failures."""


class InteraktTransientError(InteraktError):
    """Network failure or 5xx \u2014 retried by the client and surfaced
    only when retries are exhausted. Caller should mark `FAILED` and
    let a follow-up reconciliation worker re-attempt later.
    """


class InteraktPermanentError(InteraktError):
    """4xx response \u2014 do NOT retry. The journey handler should pick a
    fallback (e.g. switch to template, escalate to assisted support).
    """


@dataclass(frozen=True, slots=True)
class InteraktSendResult:
    """Successful response from `POST /v1/public/message/`."""

    interakt_message_id: str
    raw_response: dict[str, Any]


class InteraktClient:
    """Stateful HTTP wrapper. One instance per process."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings
        self._owns_http_client = http_client is None
        self._http = http_client or self._build_http_client(settings)
        self._sleep: Callable[[float], Awaitable[None]] = sleep or asyncio.sleep

    @staticmethod
    def _build_http_client(settings: AppSettings) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            connect=settings.interakt_timeout_connect_seconds,
            read=settings.interakt_timeout_read_seconds,
            write=settings.interakt_timeout_read_seconds,
            pool=settings.interakt_timeout_connect_seconds,
        )
        # Use the OS trust store (Windows / macOS keychain / Linux CA
        # bundle) instead of certifi so corporate MITM CAs installed
        # in the system store are honored. Falls back gracefully if
        # `truststore` is missing.
        verify: Any = (
            truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT) if truststore is not None else True
        )
        return httpx.AsyncClient(
            base_url=settings.interakt_base_url.rstrip("/"),
            timeout=timeout,
            verify=verify,
            headers={
                "Authorization": f"Basic {settings.interakt_api_key.get_secret_value()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def send(
        self,
        intent: OutboundIntent,
        *,
        callback_data: str,
    ) -> InteraktSendResult:
        """Send `intent` to Interakt with the supplied `callback_data`.

        Retries network / 5xx failures up to 4 attempts with
        exponential backoff + jitter. 4xx responses raise
        `InteraktPermanentError` immediately.
        """
        body = build_request_body(intent, callback_data=callback_data)

        async for attempt in AsyncRetrying(
            reraise=True,
            stop=stop_after_attempt(4),
            wait=wait_random_exponential(multiplier=0.5, max=8),
            retry=retry_if_exception_type(InteraktTransientError),
            sleep=self._sleep,
        ):
            with attempt:
                return await self._do_send(body)
        # `AsyncRetrying(reraise=True)` ensures the loop above always
        # returns or raises. The line below is unreachable but keeps
        # mypy + ruff happy.
        msg = "AsyncRetrying exhausted without raising"  # pragma: no cover
        raise InteraktError(msg)  # pragma: no cover

    async def _do_send(self, body: dict[str, Any]) -> InteraktSendResult:
        try:
            response = await self._http.post(_INTERAKT_SEND_PATH, json=body)
        except httpx.HTTPError as exc:
            msg = f"Interakt send failed at the transport layer: {exc!s}"
            raise InteraktTransientError(msg) from exc

        if response.status_code == _HTTP_TOO_MANY_REQUESTS:
            # Interakt-side rate limiting — retry with exponential
            # backoff. We do NOT cap RPS on our side; we react when
            # the provider tells us to slow down.
            msg = f"Interakt send rate-limited (429): {response.text[:300]!r}"
            raise InteraktTransientError(msg)
        if _HTTP_SERVER_ERROR <= response.status_code < _HTTP_LIMIT:
            msg = f"Interakt send returned {response.status_code}: {response.text[:300]!r}"
            raise InteraktTransientError(msg)
        if _HTTP_BAD_REQUEST <= response.status_code < _HTTP_SERVER_ERROR:
            msg = f"Interakt send rejected with {response.status_code}: {response.text[:500]!r}"
            raise InteraktPermanentError(msg)

        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            msg = f"Interakt send returned non-JSON body: {response.text[:300]!r}"
            raise InteraktTransientError(msg) from exc

        message_id = payload.get("id")
        if not isinstance(message_id, str) or not message_id:
            # Some Interakt error envelopes return 200 + result=false.
            if payload.get("result") is False:
                msg = f"Interakt send returned result=false: {payload!r}"
                raise InteraktPermanentError(msg)
            msg = f"Interakt send response missing 'id': {payload!r}"
            raise InteraktTransientError(msg)
        return InteraktSendResult(interakt_message_id=message_id, raw_response=payload)


# ---------------------------------------------------------------------------
# Wire-shape builders
# ---------------------------------------------------------------------------


def build_request_body(
    intent: OutboundIntent,
    *,
    callback_data: str,
) -> dict[str, Any]:
    """Translate an `OutboundIntent` to the Interakt JSON envelope."""
    base: dict[str, Any] = {
        "fullPhoneNumber": intent.full_phone_number,
        "callbackData": callback_data,
    }
    if intent.kind == "TEXT":
        if intent.text is None:
            msg = "TEXT OutboundIntent must have `text`"
            raise ValueError(msg)
        base["type"] = "Text"
        base["data"] = {"message": intent.text}
        return base
    if intent.kind == "BUTTONS":
        if intent.text is None or not intent.buttons:
            msg = "BUTTONS OutboundIntent must have `text` and at least one button"
            raise ValueError(msg)
        base["type"] = "InteractiveButton"
        base["data"] = {
            "message": {
                "type": "button",
                "body": {"text": intent.text},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": btn.id, "title": btn.title},
                        }
                        for btn in intent.buttons
                    ]
                },
            }
        }
        return base
    if intent.kind == "TEMPLATE":
        if not intent.template_name:
            msg = "TEMPLATE OutboundIntent must have `template_name`"
            raise ValueError(msg)
        template: dict[str, Any] = {
            "name": intent.template_name,
            "languageCode": intent.template_locale or "en",
        }
        if intent.body_values is not None:
            template["bodyValues"] = list(intent.body_values)
        if intent.header_values is not None:
            template["headerValues"] = list(intent.header_values)
        if intent.button_values is not None:
            template["buttonValues"] = {k: list(v) for k, v in intent.button_values.items()}
        if intent.file_name is not None:
            template["fileName"] = intent.file_name
        if intent.is_flow_template:
            template["is_flow_template"] = True
        base["type"] = "Template"
        base["template"] = template
        return base
    msg = f"Unsupported OutboundIntent kind: {intent.kind!r}"
    raise ValueError(msg)


__all__ = [
    "InteraktClient",
    "InteraktError",
    "InteraktPermanentError",
    "InteraktSendResult",
    "InteraktTransientError",
    "build_request_body",
]
