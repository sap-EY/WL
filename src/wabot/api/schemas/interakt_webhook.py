"""Pydantic models for inbound Interakt webhook events.

The schema is **defensive on purpose**: Interakt's payload contains many
optional/contextual fields whose shape varies across event types
(`message_received`, `message_api_*`). We therefore:

* validate only the fields we depend on (top-level `type`, the message
  id, the customer phone),
* keep the rest as ``dict[str, Any]`` so the raw payload can be
  persisted byte-for-byte,
* never reject an event because of an unknown sub-field — the event is
  always stored first and reasoned about later by the normalizer.

The only hard contract is **the envelope must declare a `type`** and
the message-bearing variants must declare a message id; otherwise
Interakt has sent something we cannot route, and we 422.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Known event-type strings from `interakt_webhook.md`. The list is
# closed for *routing* purposes (we recognise these), but we don't
# error on unknown values — they are persisted and skipped by the
# normalizer.
EVENT_TYPE_RECEIVED = "message_received"
EVENT_TYPE_API_SENT = "message_api_sent"
EVENT_TYPE_API_DELIVERED = "message_api_delivered"
EVENT_TYPE_API_READ = "message_api_read"
EVENT_TYPE_API_FAILED = "message_api_failed"
EVENT_TYPE_API_CLICKED = "message_api_clicked"
EVENT_TYPE_API_FLOW_RESPONSE = "message_api_flow_response"

KNOWN_EVENT_TYPES: frozenset[str] = frozenset(
    {
        EVENT_TYPE_RECEIVED,
        EVENT_TYPE_API_SENT,
        EVENT_TYPE_API_DELIVERED,
        EVENT_TYPE_API_READ,
        EVENT_TYPE_API_FAILED,
        EVENT_TYPE_API_CLICKED,
        EVENT_TYPE_API_FLOW_RESPONSE,
    }
)


class _Open(BaseModel):
    """Base config that allows additional fields without losing them."""

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class InteraktCustomer(_Open):
    """`data.customer` block. Only the phone number is required for routing."""

    channel_phone_number: str | None = Field(default=None)
    phone_number: str | None = Field(default=None)
    country_code: str | None = Field(default=None)


class InteraktMessage(_Open):
    """`data.message` block.

    `id` is the Interakt-side message identifier; combined with the
    event `type` and `message_status` it forms the dedupe key.
    """

    id: str | None = Field(default=None)
    message_status: str | None = Field(default=None)
    is_template_message: bool | None = Field(default=None)
    message_content_type: str | None = Field(default=None)
    message: Any | None = Field(default=None)
    meta_data: dict[str, Any] = Field(default_factory=dict)


class InteraktData(_Open):
    customer: InteraktCustomer = Field(default_factory=InteraktCustomer)
    message: InteraktMessage = Field(default_factory=InteraktMessage)


class InteraktEventBlock(_Open):
    """`event` block — only present on click events."""

    callbackData: str | None = Field(default=None)
    click_type: str | None = Field(default=None)
    button_text: str | None = Field(default=None)
    button_link: str | None = Field(default=None)
    click_timestamp: str | None = Field(default=None)


class InteraktEnvelope(_Open):
    """Top-level webhook envelope."""

    version: str | None = Field(default=None)
    timestamp: str | None = Field(default=None)
    type: str = Field(min_length=1)
    data: InteraktData = Field(default_factory=InteraktData)
    event: InteraktEventBlock | None = Field(default=None)

    # ----- Convenience accessors used by the router -----

    @property
    def interakt_message_id(self) -> str | None:
        return self.data.message.id

    @property
    def message_status(self) -> str | None:
        return self.data.message.message_status

    @property
    def full_phone_number(self) -> str | None:
        """Best-effort extraction of the canonical phone identifier.

        We always prefer `channel_phone_number` (digits-only,
        country-code-prefixed) since that is what Interakt accepts on
        outbound calls under the `fullPhoneNumber` contract.
        """
        cust = self.data.customer
        if cust.channel_phone_number:
            return cust.channel_phone_number
        if cust.country_code and cust.phone_number:
            cc = cust.country_code.lstrip("+")
            return f"{cc}{cust.phone_number}"
        return cust.phone_number


WebhookAck = Literal["ok", "duplicate"]


class WebhookAckResponse(BaseModel):
    """Response body for `/webhooks/.../interakt`. Always returns 200."""

    status: WebhookAck
    event_id: str | None = None
