"""Outbound intent model.

Journey handlers emit `OutboundIntent` instances; the orchestrator
collects them post-transition and hands them to
`services.outbound_pipeline.OutboundPipeline.dispatch` which:

1. Persists an `outbound_message` row in `PENDING_SEND` state with a
   deterministic `idempotency_key` (so retries do not duplicate).
2. Computes `callbackData = "{outbound_message_id}|{correlation_id}"`
   and patches the row in-place.
3. Calls Interakt via `adapters.interakt.client.InteraktClient`.
4. On success: `mark_sent` with the Interakt-returned message id.
   On 4xx: `mark_status(FAILED)` with the failure reason.

Handlers must NEVER call Interakt directly. The intent contract is
the only seam between the journey state machine and the wire format.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OutboundKindLiteral = Literal["TEXT", "BUTTONS", "TEMPLATE"]


class InteractiveButton(BaseModel):
    """One reply button on an `InteractiveButton` session message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=256)
    """Stable per-prompt button id (echoed back as `reply.id`)."""

    title: str = Field(min_length=1, max_length=20)
    """User-visible button label (WhatsApp limit: 20 chars)."""


class OutboundIntent(BaseModel):
    """Wire-shape-agnostic description of a single outbound message.

    The dispatcher resolves this into the right Interakt JSON payload
    (`Text`, `InteractiveButton`, or `Template`) and fills in the
    `callbackData` after the `outbound_message` row is persisted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: OutboundKindLiteral
    """Wire kind. Drives both Interakt's `type` field and the
    `outbound_message.kind` enum value."""

    full_phone_number: str = Field(min_length=8, max_length=20)
    """E.164 without the leading `+`. Mapped to `fullPhoneNumber`."""

    symbol: str = Field(min_length=1, max_length=128)
    """Catalog symbol (e.g. `MSG_REG_FULL_DETAILS_PROMPT`).

    Participates in the `idempotency_key` so two intents emitted by
    the same handler invocation for the same correlation produce
    distinct rows, while a retry with the same parameters reuses one.
    """

    # --- TEXT / BUTTONS --------------------------------------------------
    text: str | None = None
    buttons: tuple[InteractiveButton, ...] | None = None

    # --- TEMPLATE --------------------------------------------------------
    template_name: str | None = None
    template_locale: str | None = "en"
    body_values: tuple[str, ...] | None = None
    header_values: tuple[str, ...] | None = None
    button_values: dict[str, tuple[str, ...]] | None = None
    file_name: str | None = None
    is_flow_template: bool = False
    """When True, Interakt is told to render this template as a
    WhatsApp Flow (form) launcher. The flow definition itself lives
    inside the template configuration in Interakt — we only flip the
    flag on the wire."""
