"""Outbound status webhook handler.

Phase 10 applies Interakt lifecycle events (`sent`, `delivered`,
`read`, `failed`, `clicked`) to the durable `outbound_message` row.
The normalizer has already reduced provider-specific shapes into a
`CanonicalInboundEvent`; this handler only resolves the outbound row
and applies a monotonic status transition.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wabot.data.repositories.outbound_repo import OutboundRepository
from wabot.domain.enums import OutboundStatus
from wabot.domain.events import EventKind
from wabot.domain.journeys.base import register_outbound_status_handler
from wabot.infra.logging import get_logger
from wabot.infra.metrics import inc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from wabot.domain.events import CanonicalInboundEvent

logger = get_logger(__name__)


_STATUS_BY_KIND: dict[EventKind, OutboundStatus] = {
    EventKind.OUTBOUND_SENT: OutboundStatus.SENT,
    EventKind.OUTBOUND_DELIVERED: OutboundStatus.DELIVERED,
    EventKind.OUTBOUND_READ: OutboundStatus.READ,
    EventKind.OUTBOUND_FAILED: OutboundStatus.FAILED,
    EventKind.OUTBOUND_CLICKED: OutboundStatus.CLICKED,
}


class OutboundStatusWebhookHandler:
    """Updates `outbound_message` from status/click webhooks."""

    async def handle(
        self,
        *,
        event: CanonicalInboundEvent,
        session: AsyncSession,
    ) -> None:
        status = _STATUS_BY_KIND.get(event.event_kind)
        if status is None:
            logger.warning(
                "wabot.outbound_status.unsupported_kind",
                event_kind=event.event_kind.value,
                interakt_message_id=event.interakt_message_id,
            )
            inc(
                "wabot_outbound_status_events_total",
                labels={"kind": event.event_kind.value, "outcome": "unsupported"},
            )
            return

        repo = OutboundRepository(session)
        row = None
        if event.referenced_outbound_message_id is not None:
            row = await repo.get_by_id(event.referenced_outbound_message_id)
        if row is None:
            row = await repo.get_by_interakt_id(event.interakt_message_id)
        if row is None:
            logger.warning(
                "wabot.outbound_status.unmatched",
                event_kind=event.event_kind.value,
                interakt_message_id=event.interakt_message_id,
                referenced_outbound_message_id=(
                    str(event.referenced_outbound_message_id)
                    if event.referenced_outbound_message_id
                    else None
                ),
            )
            inc(
                "wabot_outbound_status_events_total",
                labels={"kind": event.event_kind.value, "outcome": "unmatched"},
            )
            return

        if row.interakt_message_id is None:
            row.interakt_message_id = event.interakt_message_id
        repo.apply_status(
            row,
            status=status,
            at=event.received_at,
            failure_reason=event.failure_reason,
            clicked_button_text=event.button_text,
        )
        logger.info(
            "wabot.outbound_status.applied",
            outbound_id=str(row.id),
            event_kind=event.event_kind.value,
            status=status.value,
        )
        inc(
            "wabot_outbound_status_events_total",
            labels={"kind": event.event_kind.value, "outcome": "applied"},
        )


register_outbound_status_handler(OutboundStatusWebhookHandler())


__all__ = ["OutboundStatusWebhookHandler"]
