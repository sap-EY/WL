"""Interakt webhook → `CanonicalInboundEvent` normalizer.

This module is the **single place** in the codebase that understands
Interakt's wire format. Everything downstream (journey handlers,
status updaters, observability) reads `CanonicalInboundEvent` only.

Hard rules:

* **Pure**: no I/O, no time.now(), no globals. Easy to unit-test
  against fixture payloads. The caller (Phase 5 worker) provides the
  `webhook_event_raw.id`, the correlation id, and the raw payload it
  loaded from Postgres.
* **Defensive**: Interakt occasionally adds new fields and
  occasionally omits old ones. We never raise on shape drift in
  fields we don't depend on; we *do* raise on missing required
  routing fields (`type`, `data.message.id`, `full_phone_number`).
* **Forward-stable**: status events keep their order
  (`Sent < Delivered < Read < Failed`) intact; the worker uses that.
* **Click events**: Interakt sends two shapes (QR vs CTA). The QR
  shape stores click metadata under `data.message.meta_data` (with
  `button_payload.payload.text` carrying the user's button label);
  the CTA shape stores it under the top-level `event` block. Both
  shapes carry `callbackData` — sometimes only on the CTA `event`
  block, sometimes only inside `data.message.meta_data.source_data`.
  We check every documented location.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from wabot.api.schemas.interakt_webhook import (
    EVENT_TYPE_API_CLICKED,
    EVENT_TYPE_API_DELIVERED,
    EVENT_TYPE_API_FAILED,
    EVENT_TYPE_API_FLOW_RESPONSE,
    EVENT_TYPE_API_READ,
    EVENT_TYPE_API_SENT,
    EVENT_TYPE_RECEIVED,
    InteraktEnvelope,
)
from wabot.domain.events import CanonicalInboundEvent, ClickType, EventKind

if TYPE_CHECKING:
    from collections.abc import Mapping


class NormalizationError(ValueError):
    """The webhook payload could not be turned into a canonical event."""


class UnsupportedEventTypeError(NormalizationError):
    """The event type is recognised by Interakt but not modelled here."""


_OUTBOUND_STATUS_KIND: dict[str, EventKind] = {
    EVENT_TYPE_API_SENT: EventKind.OUTBOUND_SENT,
    EVENT_TYPE_API_DELIVERED: EventKind.OUTBOUND_DELIVERED,
    EVENT_TYPE_API_READ: EventKind.OUTBOUND_READ,
    EVENT_TYPE_API_FAILED: EventKind.OUTBOUND_FAILED,
}


def normalize(
    *,
    raw_event_id: UUID,
    correlation_id: str,
    payload: Mapping[str, Any],
) -> CanonicalInboundEvent:
    """Translate a stored webhook payload into a `CanonicalInboundEvent`.

    Raises:
        NormalizationError: required routing fields are missing.
        UnsupportedEventTypeError: ``payload['type']`` is unknown.
    """
    envelope = _coerce_envelope(payload)

    interakt_message_id = envelope.interakt_message_id
    if not interakt_message_id:
        msg = "Webhook payload is missing data.message.id"
        raise NormalizationError(msg)

    full_phone_number = envelope.full_phone_number
    if not full_phone_number:
        msg = "Webhook payload is missing the customer phone number"
        raise NormalizationError(msg)

    received_at = _extract_received_at(envelope, payload)
    customer_id = _extract_customer_id(envelope.data.customer)
    callback_data = _extract_callback_data(envelope)
    referenced_outbound = _parse_referenced_outbound(callback_data)

    event_type = envelope.type
    if event_type == EVENT_TYPE_RECEIVED:
        event_kind, text, button_text = _classify_received(envelope)
        # Some `message_received` payloads carry InteractiveFlowReply
        # form submissions instead of plain text / buttons (form was
        # rendered inside a session message rather than a template
        # send). Treat them identically to message_api_flow_response.
        form_response = _extract_form_response(envelope)
        if form_response is not None:
            event_kind = EventKind.USER_FORM_REPLY
            text = None
            button_text = None
        return CanonicalInboundEvent(
            correlation_id=correlation_id,
            raw_event_id=raw_event_id,
            event_kind=event_kind,
            interakt_message_id=interakt_message_id,
            interakt_customer_id=customer_id,
            full_phone_number=full_phone_number,
            text=text,
            button_text=button_text,
            click_type=None,
            callback_data=callback_data,
            referenced_outbound_message_id=referenced_outbound,
            failure_reason=None,
            form_response=form_response,
            received_at=received_at,
        )

    if event_type == EVENT_TYPE_API_FLOW_RESPONSE:
        form_response = _extract_form_response(envelope)
        if form_response is None:
            msg = "message_api_flow_response missing data.message.message.nfm_reply.response_json"
            raise NormalizationError(msg)
        return CanonicalInboundEvent(
            correlation_id=correlation_id,
            raw_event_id=raw_event_id,
            event_kind=EventKind.USER_FORM_REPLY,
            interakt_message_id=interakt_message_id,
            interakt_customer_id=customer_id,
            full_phone_number=full_phone_number,
            text=None,
            button_text=None,
            click_type=None,
            callback_data=callback_data,
            referenced_outbound_message_id=referenced_outbound,
            failure_reason=None,
            form_response=form_response,
            received_at=received_at,
        )

    if event_type in _OUTBOUND_STATUS_KIND:
        kind = _OUTBOUND_STATUS_KIND[event_type]
        failure_reason = None
        if kind is EventKind.OUTBOUND_FAILED:
            failure_reason = _str_or_none(
                envelope.data.message.model_dump().get("channel_failure_reason")
            )
        return CanonicalInboundEvent(
            correlation_id=correlation_id,
            raw_event_id=raw_event_id,
            event_kind=kind,
            interakt_message_id=interakt_message_id,
            interakt_customer_id=customer_id,
            full_phone_number=full_phone_number,
            text=None,
            button_text=None,
            click_type=None,
            callback_data=callback_data,
            referenced_outbound_message_id=referenced_outbound,
            failure_reason=failure_reason,
            received_at=received_at,
        )

    if event_type == EVENT_TYPE_API_CLICKED:
        click_type, button_text = _extract_click_details(envelope)
        return CanonicalInboundEvent(
            correlation_id=correlation_id,
            raw_event_id=raw_event_id,
            event_kind=EventKind.OUTBOUND_CLICKED,
            interakt_message_id=interakt_message_id,
            interakt_customer_id=customer_id,
            full_phone_number=full_phone_number,
            text=None,
            button_text=button_text,
            click_type=click_type,
            callback_data=callback_data,
            referenced_outbound_message_id=referenced_outbound,
            failure_reason=None,
            received_at=received_at,
        )

    msg = f"Unsupported Interakt event type: {event_type!r}"
    raise UnsupportedEventTypeError(msg)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _coerce_envelope(payload: Mapping[str, Any]) -> InteraktEnvelope:
    try:
        return InteraktEnvelope.model_validate(payload)
    except Exception as exc:
        msg = f"Webhook payload failed envelope validation: {exc}"
        raise NormalizationError(msg) from exc


def _classify_received(
    envelope: InteraktEnvelope,
) -> tuple[EventKind, str | None, str | None]:
    """Map a `message_received` event to (kind, text, button_text).

    Interakt classifies user replies via `data.message.message_content_type`:

    * ``"Text"`` → free-text (`USER_TEXT`).
    * ``"Interactive"`` for button replies → `USER_BUTTON_REPLY`. The
      reply text lives either inside `meta_data.button_payload.payload.text`
      (quick reply) or inside `data.message.message` itself.
    * Anything matching list reply markers → `USER_LIST_REPLY`.
    * Unknown content types fall back to `USER_TEXT` with `text=None`
      so journey handlers see *something* rather than failing — the
      raw row is still on disk for audit.
    """
    msg = envelope.data.message
    content_type_raw = msg.message_content_type or ""
    content_type = content_type_raw.lower()
    text_value = _str_or_none(msg.message)
    button_text = _extract_button_reply_text(msg.meta_data)

    if content_type == "text":
        return EventKind.USER_TEXT, text_value, None

    if "list" in content_type:
        # `Interactive` list replies surface their selected option in
        # the same `meta_data.button_payload.payload.text` slot in
        # practice; if not, fall back to the message body.
        return (
            EventKind.USER_LIST_REPLY,
            None,
            button_text or text_value,
        )

    if "interactive" in content_type or "button" in content_type or button_text:
        return EventKind.USER_BUTTON_REPLY, None, button_text or text_value

    # Unknown / future content type: treat as free text so the journey
    # has a chance to react. Logged at INFO upstream by the worker.
    return EventKind.USER_TEXT, text_value, None


def _extract_click_details(
    envelope: InteraktEnvelope,
) -> tuple[ClickType | None, str | None]:
    """Pull `click_type` and `button_text` from either click variant."""
    click_type: ClickType | None = None
    button_text: str | None = None

    if envelope.event is not None:
        ct = _str_or_none(envelope.event.click_type)
        if ct in {"QR", "CTA"}:
            click_type = ct  # type: ignore[assignment]
        button_text = _str_or_none(envelope.event.button_text)

    meta = envelope.data.message.meta_data or {}
    if click_type is None:
        meta_ct = _str_or_none(meta.get("click_type"))
        if meta_ct in {"QR", "CTA"}:
            click_type = meta_ct  # type: ignore[assignment]

    if not button_text:
        button_text = _str_or_none(meta.get("button_text"))

    if not button_text:
        # QR shape places the user-visible label deep under
        # `meta_data.button_payload.payload.text` (per Interakt docs).
        bp = meta.get("button_payload")
        if isinstance(bp, dict):
            payload = bp.get("payload")
            if isinstance(payload, dict):
                button_text = _str_or_none(payload.get("text"))

    return click_type, button_text


def _extract_button_reply_text(meta_data: Mapping[str, Any]) -> str | None:
    """Extract the user's chosen button label from a `message_received`
    interactive payload. See `_extract_click_details` for the dual-shape
    explanation; here we only ever see the QR shape.
    """
    bp = meta_data.get("button_payload")
    if isinstance(bp, dict):
        payload = bp.get("payload")
        if isinstance(payload, dict):
            text = _str_or_none(payload.get("text"))
            if text:
                return text
    return _str_or_none(meta_data.get("button_text"))


def _extract_callback_data(envelope: InteraktEnvelope) -> str | None:
    """Pull `callbackData` from every documented location (CTA, QR, status).

    Order of precedence:

    1. Top-level `event.callbackData` (CTA click).
    2. `data.message.meta_data.source_data.callback_data` (status events
       and QR clicks).
    3. `data.message.meta_data.callbackData` (defensive — older payloads).
    """
    if envelope.event is not None:
        cb = _str_or_none(envelope.event.callbackData)
        if cb:
            return cb

    meta = envelope.data.message.meta_data or {}
    source_data = meta.get("source_data")
    if isinstance(source_data, dict):
        cb = _str_or_none(source_data.get("callback_data")) or _str_or_none(
            source_data.get("callbackData")
        )
        if cb:
            return cb

    return _str_or_none(meta.get("callbackData")) or _str_or_none(meta.get("callback_data"))


def _parse_referenced_outbound(callback_data: str | None) -> UUID | None:
    """`callbackData = "{outbound_message_id}|{correlation_id}"`.

    Returns ``None`` for any value we did not mint ourselves (free-text
    callback data from arbitrary templates). Strict UUID parse keeps
    handlers safe.
    """
    if not callback_data or "|" not in callback_data:
        return None
    head, _, _ = callback_data.partition("|")
    head = head.strip()
    if not head:
        return None
    try:
        return UUID(head)
    except ValueError:
        return None


def _extract_received_at(envelope: InteraktEnvelope, payload: Mapping[str, Any]) -> datetime:
    """Prefer `data.message.received_at_utc`; fall back to top-level
    `timestamp`; final fallback `datetime.now(UTC)` (with a warning is
    out of scope here — the caller logs).
    """
    msg_dump = envelope.data.message.model_dump()
    raw = (
        _str_or_none(msg_dump.get("received_at_utc"))
        or _str_or_none(payload.get("timestamp"))
        or _str_or_none(envelope.timestamp)
    )
    if raw:
        parsed = _parse_iso8601(raw)
        if parsed is not None:
            return parsed
    return datetime.now(UTC)


def _extract_form_response(envelope: InteraktEnvelope) -> dict[str, Any] | None:
    """Extract `data.message.message.nfm_reply.response_json` if present.

    Returns the parsed `response_json` dict on success, or ``None`` if
    this envelope does not carry a WhatsApp Flow form submission. We do
    NOT raise on shape drift here; the caller decides whether the
    absence is an error (flow-response event type) or expected
    (regular `message_received`).
    """
    msg = envelope.data.message
    content_type = (msg.message_content_type or "").lower()
    inner = msg.message
    if not isinstance(inner, dict):
        return None
    if content_type and content_type != "interactiveflowreply":
        return None
    nfm = inner.get("nfm_reply")
    if not isinstance(nfm, dict):
        return None
    response_json = nfm.get("response_json")
    if not isinstance(response_json, dict):
        return None
    return dict(response_json)


def _parse_iso8601(value: str) -> datetime | None:
    """Tolerate Interakt's mix of `+00:00` and naive UTC strings."""
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _extract_customer_id(customer: Any) -> str | None:
    """`InteraktCustomer` has `extra="allow"`, so `id` is on the dump."""
    if customer is None:
        return None
    dumped = customer.model_dump() if hasattr(customer, "model_dump") else dict(customer)
    return _str_or_none(dumped.get("id"))


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)
