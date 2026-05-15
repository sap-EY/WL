"""Outbound dispatch pipeline.

Consumes the `OutboundIntent` tuple a journey handler returned and
turns it into actual Interakt API calls **plus** a durable
`outbound_message` row per intent. The pipeline is the only path
allowed to call `InteraktClient.send` \u2014 that keeps idempotency,
chain-of-context (`callbackData`), and status reconciliation
centralised.

Flow per intent (\u00a79.1\u20139.5 of `implementation_plan.md`):

1. **Open a short transaction.** Compute a deterministic
   `idempotency_key`. `OutboundRepository.create_pending` either
   inserts a fresh `PENDING_SEND` row or returns the existing row
   when the key collides (replay-safe).
2. **Stamp `callback_data`.** When the row is fresh, we now know its
   primary-key `id` and update `callback_data` to
   `f"{outbound.id}|{correlation_id}"`. Re-played rows keep their
   original `callback_data` so the historical chain still resolves.
   The transaction commits.
3. **Call Interakt** outside the DB transaction so the connection is
   never held while talking to a third-party. Network / 5xx are
   retried inside `InteraktClient.send`; only `InteraktPermanentError`
   reaches us here.
4. **Open a second short transaction.** On success: `mark_sent` with
   the Interakt-returned message id. On permanent failure:
   `mark_status(FAILED)` with the captured reason.

The pipeline does not raise on individual intent failures \u2014 it
returns a `DispatchResult` per intent so the orchestrator can log
the aggregate without aborting unrelated intents in the same batch.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from wabot.adapters.interakt import InteraktPermanentError
from wabot.data.db import session_scope
from wabot.data.models.outbound import OutboundMessage
from wabot.data.repositories.conversation_repo import ConversationRepository
from wabot.data.repositories.outbound_repo import OutboundRepository
from wabot.domain.enums import OutboundKind, OutboundStatus
from wabot.infra.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from wabot.adapters.interakt import InteraktClient
    from wabot.domain.outbound import OutboundIntent

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """Per-intent outcome returned to the caller for observability."""

    outbound_id: uuid.UUID
    interakt_message_id: str | None
    status: OutboundStatus
    failure_reason: str | None = None


class OutboundPipeline:
    """Sends each intent through Interakt and persists its lifecycle."""

    def __init__(self, *, client: InteraktClient) -> None:
        self._client = client

    async def dispatch(
        self,
        intents: Sequence[OutboundIntent],
        *,
        doctor_id: uuid.UUID,
        state_when_sent: str | None,
        correlation_id: str,
        conversation_session_id: uuid.UUID | None = None,
    ) -> list[DispatchResult]:
        """Persist + send each intent in `intents` order.

        Per-intent failures are isolated: a permanent 4xx on intent #1
        does not stop intent #2.
        """
        results: list[DispatchResult] = []
        for index, intent in enumerate(intents):
            log = logger.bind(
                doctor_id=str(doctor_id),
                correlation_id=correlation_id,
                intent_index=index,
                symbol=intent.symbol,
                kind=intent.kind,
            )
            results.append(
                await self._dispatch_one(
                    intent,
                    doctor_id=doctor_id,
                    state_when_sent=state_when_sent,
                    correlation_id=correlation_id,
                    sequence=index,
                    conversation_session_id=conversation_session_id,
                    log=log,
                )
            )
        return results

    async def _dispatch_one(
        self,
        intent: OutboundIntent,
        *,
        doctor_id: uuid.UUID,
        state_when_sent: str | None,
        correlation_id: str,
        sequence: int,
        conversation_session_id: uuid.UUID | None,
        log: object,
    ) -> DispatchResult:
        idempotency_key = compute_idempotency_key(
            doctor_id=doctor_id,
            state_when_sent=state_when_sent,
            correlation_id=correlation_id,
            sequence=sequence,
            intent=intent,
        )
        outbound_id, callback_data = await self._persist_pending(
            intent=intent,
            doctor_id=doctor_id,
            state_when_sent=state_when_sent,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

        try:
            send_result = await self._client.send(intent, callback_data=callback_data)
        except InteraktPermanentError as exc:
            reason = str(exc)
            log.warning("wabot.outbound_pipeline.permanent_failure", error=reason)  # type: ignore[attr-defined]
            await self._mark_failed(outbound_id=outbound_id, reason=reason)
            return DispatchResult(
                outbound_id=outbound_id,
                interakt_message_id=None,
                status=OutboundStatus.FAILED,
                failure_reason=reason,
            )
        except Exception as exc:  # transient retries exhausted
            reason = f"transient: {exc!s}"
            log.warning("wabot.outbound_pipeline.transient_failure", error=reason)  # type: ignore[attr-defined]
            await self._mark_failed(outbound_id=outbound_id, reason=reason)
            return DispatchResult(
                outbound_id=outbound_id,
                interakt_message_id=None,
                status=OutboundStatus.FAILED,
                failure_reason=reason,
            )

        await self._mark_sent(
            outbound_id=outbound_id,
            interakt_message_id=send_result.interakt_message_id,
        )
        await self._log_conversation_outbound(
            doctor_id=doctor_id,
            conversation_session_id=conversation_session_id,
            intent=intent,
            interakt_message_id=send_result.interakt_message_id,
            callback_data=callback_data,
            correlation_id=correlation_id,
        )
        log.info(  # type: ignore[attr-defined]
            "wabot.outbound_pipeline.sent",
            outbound_id=str(outbound_id),
            interakt_message_id=send_result.interakt_message_id,
        )
        return DispatchResult(
            outbound_id=outbound_id,
            interakt_message_id=send_result.interakt_message_id,
            status=OutboundStatus.SENT,
        )

    # ------------------------------------------------------------------
    # DB helpers (each owns a short transaction)
    # ------------------------------------------------------------------
    async def _persist_pending(
        self,
        *,
        intent: OutboundIntent,
        doctor_id: uuid.UUID,
        state_when_sent: str | None,
        correlation_id: str,
        idempotency_key: str,
    ) -> tuple[uuid.UUID, str]:
        async with session_scope() as session:
            repo = OutboundRepository(session)
            row = await repo.create_pending(
                doctor_id=doctor_id,
                kind=_kind_to_enum(intent.kind),
                template_name=intent.template_name,
                payload=intent.model_dump(mode="json"),
                idempotency_key=idempotency_key,
                callback_data="PENDING_SEND",
                state_when_sent=state_when_sent,
                correlation_id=_safe_uuid(correlation_id),
            )
            # If the row is fresh its callback_data is the placeholder
            # default; rewrite it to carry the chain-of-context. Replays
            # of the same idempotency_key keep the original value.
            if row.callback_data == "PENDING_SEND":
                row.callback_data = f"{row.id}|{correlation_id}"
            return row.id, row.callback_data

    async def _mark_sent(
        self,
        *,
        outbound_id: uuid.UUID,
        interakt_message_id: str,
    ) -> None:
        async with session_scope() as session:
            repo = OutboundRepository(session)
            await repo.mark_sent(
                outbound_id,
                interakt_message_id=interakt_message_id,
                sent_at=datetime.now(UTC),
            )

    async def _log_conversation_outbound(
        self,
        *,
        doctor_id: uuid.UUID,
        conversation_session_id: uuid.UUID | None,
        intent: OutboundIntent,
        interakt_message_id: str | None,
        callback_data: str | None,
        correlation_id: str,
    ) -> None:
        """Append an OUTBOUND row to `conversation_message`.

        Best-effort: the message has already been sent over the wire,
        so any DB failure here must NOT propagate.
        """
        try:
            async with session_scope() as session:
                conv_repo = ConversationRepository(session)
                if conversation_session_id is not None:
                    conv_session_id = conversation_session_id
                else:
                    conv_session = await conv_repo.get_or_create_active_session(doctor_id)
                    conv_session_id = conv_session.id
                await conv_repo.log_outbound(
                    session_id=conv_session_id,
                    doctor_id=doctor_id,
                    text=intent.text,
                    payload=intent.model_dump(mode="json"),
                    interakt_msg_id=interakt_message_id,
                    callback_data=callback_data,
                    correlation_id=_safe_uuid(correlation_id),
                )
                await conv_repo.touch(conv_session_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "wabot.outbound_pipeline.conversation_log_failed",
                error=str(exc),
                doctor_id=str(doctor_id),
            )

    async def _mark_failed(
        self,
        *,
        outbound_id: uuid.UUID,
        reason: str,
    ) -> None:
        async with session_scope() as session:
            row = await session.get(OutboundMessage, outbound_id)
            if row is None:
                return
            row.status = OutboundStatus.FAILED
            row.failed_at = datetime.now(UTC)
            row.failure_reason = reason[:1000]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compute_idempotency_key(
    *,
    doctor_id: uuid.UUID,
    state_when_sent: str | None,
    correlation_id: str,
    sequence: int,
    intent: OutboundIntent,
) -> str:
    """Deterministic key so retries collapse onto one row.

    Mirrors \u00a79.2: includes doctor, journey state, sequence within the
    handler invocation, and a payload hash so two intents that *look*
    identical but differ in body still get distinct rows.
    """
    payload_dump = json.dumps(intent.model_dump(mode="json"), sort_keys=True)
    payload_hash = hashlib.sha256(payload_dump.encode("utf-8")).hexdigest()
    components = [
        str(doctor_id),
        state_when_sent or "-",
        correlation_id,
        str(sequence),
        intent.symbol,
        payload_hash,
    ]
    digest = hashlib.sha256("|".join(components).encode("utf-8")).hexdigest()
    return f"out_{digest}"


def _kind_to_enum(kind: str) -> OutboundKind:
    return {
        "TEXT": OutboundKind.TEXT,
        "BUTTONS": OutboundKind.BUTTONS,
        "TEMPLATE": OutboundKind.TEMPLATE,
    }[kind]


def _safe_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return None


__all__ = [
    "DispatchResult",
    "OutboundPipeline",
    "compute_idempotency_key",
]
