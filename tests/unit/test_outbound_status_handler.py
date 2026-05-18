"""Tests for outbound status webhook handling."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import wabot.domain.journeys.status as status_mod
from wabot.domain.enums import OutboundStatus
from wabot.domain.events import CanonicalInboundEvent, EventKind
from wabot.domain.journeys.status import OutboundStatusWebhookHandler


def _event(
    *,
    kind: EventKind = EventKind.OUTBOUND_DELIVERED,
    interakt_message_id: str = "im-1",
    referenced_outbound_message_id: uuid.UUID | None = None,
    button_text: str | None = None,
) -> CanonicalInboundEvent:
    return CanonicalInboundEvent(
        correlation_id="11111111-1111-4111-8111-111111111111",
        raw_event_id=uuid.uuid4(),
        event_kind=kind,
        interakt_message_id=interakt_message_id,
        interakt_customer_id="cust-1",
        full_phone_number="9170000000",
        button_text=button_text,
        referenced_outbound_message_id=referenced_outbound_message_id,
        received_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_status_handler_resolves_by_callback_outbound_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outbound_id = uuid.uuid4()
    row = SimpleNamespace(
        id=outbound_id,
        interakt_message_id=None,
        status=OutboundStatus.SENT,
        sent_at=None,
        delivered_at=None,
        read_at=None,
        failed_at=None,
        failure_reason=None,
        clicked_at=None,
        clicked_button_text=None,
    )

    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=row)
    repo.get_by_interakt_id = AsyncMock()

    def _apply_status(row_arg: Any, **kwargs: Any) -> None:
        row_arg.status = kwargs["status"]
        row_arg.delivered_at = kwargs["at"]

    repo.apply_status = MagicMock(side_effect=_apply_status)
    monkeypatch.setattr(status_mod, "OutboundRepository", lambda _session: repo)

    event = _event(referenced_outbound_message_id=outbound_id)
    await OutboundStatusWebhookHandler().handle(event=event, session=MagicMock())

    repo.get_by_id.assert_awaited_once_with(outbound_id)
    repo.get_by_interakt_id.assert_not_awaited()
    assert row.interakt_message_id == "im-1"
    assert row.status is OutboundStatus.DELIVERED


@pytest.mark.asyncio
async def test_status_handler_resolves_by_interakt_id_when_callback_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = SimpleNamespace(id=uuid.uuid4(), interakt_message_id="im-1", status=OutboundStatus.READ)
    repo = MagicMock()
    repo.get_by_interakt_id = AsyncMock(return_value=row)
    repo.apply_status = MagicMock()
    monkeypatch.setattr(status_mod, "OutboundRepository", lambda _session: repo)

    event = _event(kind=EventKind.OUTBOUND_CLICKED, button_text="Satisfied")
    await OutboundStatusWebhookHandler().handle(event=event, session=MagicMock())

    repo.get_by_interakt_id.assert_awaited_once_with("im-1")
    kwargs = repo.apply_status.call_args.kwargs
    assert kwargs["status"] is OutboundStatus.CLICKED
    assert kwargs["clicked_button_text"] == "Satisfied"


@pytest.mark.asyncio
async def test_status_handler_ignores_unmatched_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = MagicMock()
    repo.get_by_interakt_id = AsyncMock(return_value=None)
    repo.apply_status = MagicMock()
    monkeypatch.setattr(status_mod, "OutboundRepository", lambda _session: repo)

    await OutboundStatusWebhookHandler().handle(event=_event(), session=MagicMock())

    repo.apply_status.assert_not_called()
