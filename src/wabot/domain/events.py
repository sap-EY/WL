"""Canonical inbound event model.

Phase 4 output: every persisted `webhook_event_raw` row is translated by
`adapters.interakt.normalizer.normalize` into one of these objects
before the orchestrator (Phase 5) sees it. The orchestrator never
reads Interakt's wire shape — it only consumes `CanonicalInboundEvent`.

Design notes:

* The model is **closed** (`extra="forbid"`) — anything we want
  downstream must be an explicit, typed field. Forward-compat with
  Interakt schema drift happens at the normalizer, not here.
* `event_kind` is a `StrEnum` so journey handlers can branch on it
  exhaustively with `match`.
* `referenced_outbound_message_id` is parsed once at normalization
  time from `callback_data` (`"{outbound_message_id}|{correlation_id}"`)
  so handlers don't reimplement that contract.
* `received_at` is microsecond-precision UTC; matches Interakt's
  `received_at_utc` precision (see `interakt_webhook.md`).
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EventKind(StrEnum):
    """Canonical inbound event taxonomy.

    Values are stable strings — they appear in logs, metrics, and the
    orchestrator's `match` arms. Do not rename without grepping every
    handler.
    """

    USER_TEXT = "user_text"
    USER_BUTTON_REPLY = "user_button_reply"
    USER_LIST_REPLY = "user_list_reply"
    USER_FORM_REPLY = "user_form_reply"
    OUTBOUND_SENT = "outbound_sent"
    OUTBOUND_DELIVERED = "outbound_delivered"
    OUTBOUND_READ = "outbound_read"
    OUTBOUND_FAILED = "outbound_failed"
    OUTBOUND_CLICKED = "outbound_clicked"


USER_EVENT_KINDS: frozenset[EventKind] = frozenset(
    {
        EventKind.USER_TEXT,
        EventKind.USER_BUTTON_REPLY,
        EventKind.USER_LIST_REPLY,
        EventKind.USER_FORM_REPLY,
    }
)
"""Inbound user-originated events. Drive journey state transitions."""


OUTBOUND_STATUS_KINDS: frozenset[EventKind] = frozenset(
    {
        EventKind.OUTBOUND_SENT,
        EventKind.OUTBOUND_DELIVERED,
        EventKind.OUTBOUND_READ,
        EventKind.OUTBOUND_FAILED,
        EventKind.OUTBOUND_CLICKED,
    }
)
"""Status-update events for messages we sent. Update `outbound_message`."""


ClickType = Literal["QR", "CTA"]


class CanonicalInboundEvent(BaseModel):
    """Provider-agnostic inbound event consumed by the orchestrator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    correlation_id: str
    raw_event_id: UUID
    event_kind: EventKind

    interakt_message_id: str
    interakt_customer_id: str | None = None
    full_phone_number: str

    text: str | None = None
    button_text: str | None = None
    click_type: ClickType | None = None

    callback_data: str | None = None
    referenced_outbound_message_id: UUID | None = None

    failure_reason: str | None = None
    form_response: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Parsed WhatsApp Flow form payload (only set when "
            "`event_kind == USER_FORM_REPLY`). Mirrors "
            "`data.message.message.nfm_reply.response_json` from "
            "Interakt's `message_api_flow_response` webhook."
        ),
    )
    received_at: datetime = Field(
        ...,
        description="Microsecond-precision UTC timestamp from Interakt's "
        "`received_at_utc` (or top-level `timestamp` fallback).",
    )
