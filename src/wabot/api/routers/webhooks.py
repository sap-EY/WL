"""Interakt webhook ingestion endpoint.

Path: ``POST /webhooks/{secret}/interakt``

Hot-path responsibilities (must complete in <100 ms):

1. Constant-time compare the URL ``secret`` with
   ``settings.interakt_webhook_path_secret`` — wrong secret returns
   404 (we deliberately do not reveal that the path exists).
2. Parse the JSON body with `orjson` directly so we avoid FastAPI's
   default Pydantic-coerced parser, then validate via `InteraktEnvelope`.
3. Build a dedupe key ``(type, message.id, message_status)`` and try
   `WebhookDedupe.claim`. A duplicate short-circuits with 200 — no DB
   write, no enqueue.
4. Persist the raw event in `wabot.webhook_event_raw` via
   `WebhookRepository.record_if_new` (the partial unique index is the
   strong-consistency safety net).
5. Enqueue ``{event_id, type, full_phone_number, correlation_id}`` to
   the inbound broker; the orchestrator worker (Phase 5) reads from
   there.
6. Return ``200 OK`` with ``{"status": "ok" | "duplicate", "event_id": ...}``.

Failure modes:

* DB unreachable → respond 503 so Interakt retries the event.
* Broker enqueue failure after a successful DB write → log and respond
  200 anyway: the row is the source of truth and a backfill job will
  pick up `processed_at IS NULL` rows. Returning non-200 here would
  trigger Interakt retries that, by design, would dedupe at step 3
  but still pile on load.
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Annotated

import orjson
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from pydantic import ValidationError

from wabot.adapters.broker import BrokerEnqueueError, get_broker
from wabot.api.schemas.interakt_webhook import (
    EVENT_TYPE_API_CLICKED,
    EVENT_TYPE_API_DELIVERED,
    EVENT_TYPE_API_FAILED,
    EVENT_TYPE_API_FLOW_RESPONSE,
    EVENT_TYPE_API_READ,
    EVENT_TYPE_API_SENT,
    EVENT_TYPE_RECEIVED,
    KNOWN_EVENT_TYPES,
    InteraktEnvelope,
    WebhookAckResponse,
)
from wabot.cache.dedupe import WebhookDedupe, build_dedupe_key
from wabot.data.db import session_scope
from wabot.data.repositories import WebhookRepository
from wabot.infra.config import AppSettings, get_settings
from wabot.infra.correlation import get_current_correlation_id
from wabot.infra.errors import ValidationFailedError
from wabot.infra.logging import get_logger
from wabot.infra.metrics import inc

if TYPE_CHECKING:
    from wabot.adapters.broker import BrokerQueue, InboundBroker

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_USER_EVENT_TYPES = frozenset({EVENT_TYPE_RECEIVED, EVENT_TYPE_API_FLOW_RESPONSE})
_STATUS_EVENT_TYPES = frozenset(
    {
        EVENT_TYPE_API_SENT,
        EVENT_TYPE_API_DELIVERED,
        EVENT_TYPE_API_READ,
        EVENT_TYPE_API_FAILED,
        EVENT_TYPE_API_CLICKED,
    }
)


def _check_secret(provided: str, settings: AppSettings) -> None:
    """Constant-time comparison; mismatched secret looks like 404."""
    expected = settings.interakt_webhook_path_secret.get_secret_value()
    if not expected or not secrets.compare_digest(provided, expected):
        # 404 instead of 401 — leaks no information about the route.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.post(
    "/{secret}/interakt",
    response_model=WebhookAckResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive an Interakt webhook event",
)
async def receive_interakt_webhook(  # noqa: PLR0915
    request: Request,
    response: Response,
    secret: Annotated[str, Path(min_length=1, max_length=256)],
    settings: Annotated[AppSettings, Depends(get_settings)],
) -> WebhookAckResponse:
    _check_secret(secret, settings)

    raw_body = await request.body()
    try:
        payload = orjson.loads(raw_body) if raw_body else {}
    except orjson.JSONDecodeError as exc:
        raise ValidationFailedError("Webhook body is not valid JSON") from exc

    try:
        envelope = InteraktEnvelope.model_validate(payload)
    except ValidationError as exc:
        # Surfaced via the standard error envelope (422).
        raise ValidationFailedError(
            "Webhook envelope validation failed",
            details={"errors": exc.errors()},
        ) from exc

    correlation_id = get_current_correlation_id()
    event_type = envelope.type
    interakt_message_id = envelope.interakt_message_id
    full_phone_number = envelope.full_phone_number
    message_status = envelope.message_status
    is_known = event_type in KNOWN_EVENT_TYPES
    inc("wabot_webhook_received_total", labels={"type": event_type})

    # 1) Cache-level dedupe (best effort).
    dedupe_key = build_dedupe_key(
        event_type=event_type,
        interakt_message_id=interakt_message_id,
        message_status=message_status,
    )
    dedupe = WebhookDedupe()
    try:
        is_first = await dedupe.claim(dedupe_key)
    except Exception as exc:
        logger.warning("wabot.webhook.dedupe_unavailable", error=str(exc))
        is_first = True

    if not is_first:
        logger.info(
            "wabot.webhook.duplicate_short_circuit",
            event_type=event_type,
            interakt_message_id=interakt_message_id,
            message_status=message_status,
        )
        inc("wabot_webhook_duplicate_total", labels={"type": event_type, "source": "redis"})
        return WebhookAckResponse(status="duplicate")

    # 2) DB persist (durable replay log + strong dedupe).
    try:
        async with session_scope() as session:
            repo = WebhookRepository(session)
            row, is_new = await repo.record_if_new(
                event_type=event_type,
                interakt_message_id=interakt_message_id,
                full_phone_number=full_phone_number,
                payload=payload,
            )
            event_id = str(row.id)
    except Exception as exc:
        logger.error(
            "wabot.webhook.persist_failed",
            event_type=event_type,
            interakt_message_id=interakt_message_id,
            error=str(exc),
        )
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        inc("wabot_webhook_persist_failed_total", labels={"type": event_type})
        # 503 tells Interakt to retry; the body honestly reports the
        # failure rather than masquerading as a duplicate.
        return WebhookAckResponse(status="error")

    if not is_new:
        logger.info(
            "wabot.webhook.duplicate_db",
            event_type=event_type,
            interakt_message_id=interakt_message_id,
            event_id=event_id,
        )
        inc("wabot_webhook_duplicate_total", labels={"type": event_type, "source": "db"})
        return WebhookAckResponse(status="duplicate", event_id=event_id)

    # 3) Broker enqueue (best effort once DB has accepted the row).
    if is_known:
        queue = _queue_for_event_type(event_type)
        broker: InboundBroker = get_broker(settings, queue=queue)
        partition_key = full_phone_number or event_id
        broker_payload = {
            "event_id": event_id,
            "type": event_type,
            "full_phone_number": full_phone_number,
            "interakt_message_id": interakt_message_id,
            "message_status": message_status,
            "correlation_id": correlation_id,
        }
        try:
            await broker.enqueue(partition_key=partition_key, payload=broker_payload)
        except BrokerEnqueueError as exc:
            # Row is durable; janitor/replay job will catch up. Still ack 200.
            logger.error(
                "wabot.webhook.broker_enqueue_failed",
                queue=queue,
                event_type=event_type,
                event_id=event_id,
                error=str(exc),
            )
            inc(
                "wabot_webhook_enqueue_failed_total",
                labels={"type": event_type, "queue": queue},
            )
        else:
            logger.info(
                "wabot.webhook.enqueued",
                queue=queue,
                event_type=event_type,
                event_id=event_id,
            )
            inc("wabot_webhook_enqueued_total", labels={"type": event_type, "queue": queue})
    else:
        logger.info(
            "wabot.webhook.unknown_event_type_persisted",
            event_type=event_type,
            event_id=event_id,
        )
        inc("wabot_webhook_unknown_type_total", labels={"type": event_type})

    return WebhookAckResponse(status="ok", event_id=event_id)


def _queue_for_event_type(event_type: str) -> BrokerQueue:
    if event_type in _USER_EVENT_TYPES:
        return "inbound"
    if event_type in _STATUS_EVENT_TYPES:
        return "status"
    return "inbound"
