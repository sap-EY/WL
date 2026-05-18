"""Azure Service Bus broker adapter.

One adapter instance is bound to one logical queue (`inbound`,
`status`, `genai`, or `outbound`). Messages use Service Bus sessions
with ``session_id = full_phone_number`` so each doctor's sequence is
FIFO while different doctors are processed concurrently.

Throughput design (`implementation_plan.md` §10):

* ``consume`` accepts the next available session (or returns ``[]``
  when none is available within ``block_ms``) and pulls up to
  ``batch_size`` messages from that session in a single round-trip.
  All messages from one accept share a single :class:`_SessionHandle`;
  the receiver is only closed once every message it produced has been
  ``ack``-ed or ``nack``-ed.
* When the SDK's ``AutoLockRenewer`` is available we register the
  session with a 5-minute renewal window so long-running journey
  handlers do not lose the session lock mid-flight.
* Idle polls do not raise: ``OperationTimeoutError`` and the
  empty-list result from ``receive_messages`` are the documented
  "no work right now" signals and are translated to an empty list
  for the worker loop, mirroring Redis Streams' XREADGROUP block.

Lazy imports keep the module importable without ``azure-servicebus``
installed (local dev usually runs on Redis Streams); the constructor
raises clearly if the SDK is missing when ``BROKER_BACKEND=azure_servicebus``.
"""

from __future__ import annotations

import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from importlib import import_module
from typing import TYPE_CHECKING, Any

import orjson

from wabot.adapters.broker.base import (
    BrokerConsumeError,
    BrokerEnqueueError,
    BrokerQueue,
    InboundBroker,
    InboundMessage,
)
from wabot.infra.logging import get_logger

if TYPE_CHECKING:
    from wabot.infra.config import AppSettings

logger = get_logger(__name__)

# --- Lazy SDK bindings -------------------------------------------------------
# The Azure Service Bus SDK is an optional runtime dependency. We resolve the
# symbols once at import time so we never pay the importlib cost on the hot
# path, and so mypy --strict sees a single ``Any`` shape regardless of whether
# the package is installed locally.

NEXT_AVAILABLE_SESSION: Any = None
ServiceBusClient: Any = None
ServiceBusMessage: Any = None
AutoLockRenewer: Any = None
ServiceBusError: type[BaseException] = Exception
OperationTimeoutError: type[BaseException] = TimeoutError
SessionLockLostError: type[BaseException] = Exception

try:  # pragma: no cover - import depends on deployment deps
    _servicebus = import_module("azure.servicebus")
    _servicebus_aio = import_module("azure.servicebus.aio")
    _servicebus_exc = import_module("azure.servicebus.exceptions")
except ImportError:  # pragma: no cover - local tests can run without Azure SDK
    pass
else:  # pragma: no cover - exercised only when Azure SDK is installed
    NEXT_AVAILABLE_SESSION = _servicebus.NEXT_AVAILABLE_SESSION
    ServiceBusClient = _servicebus_aio.ServiceBusClient
    ServiceBusMessage = _servicebus.ServiceBusMessage
    AutoLockRenewer = getattr(_servicebus_aio, "AutoLockRenewer", None)
    ServiceBusError = _servicebus_exc.ServiceBusError
    OperationTimeoutError = _servicebus_exc.OperationTimeoutError
    SessionLockLostError = getattr(
        _servicebus_exc, "SessionLockLostError", _servicebus_exc.ServiceBusError
    )


# How long ``AutoLockRenewer`` keeps a session lock alive on our behalf.
# Five minutes comfortably covers the slowest end-to-end journey turn
# (GenAI round-trip + Interakt send) while still bounding the blast radius
# of a stuck handler.
_SESSION_RENEW_SECONDS = 300


@dataclass(slots=True)
class _SessionHandle:
    """Shared lifecycle for all messages received from one session.

    The receiver is opened in ``consume`` and stays open until every
    message it produced has been ack-ed or nack-ed; the last ack/nack
    closes it (and detaches the auto-lock-renewer).
    """

    receiver: Any
    renewer: Any | None
    messages: dict[str, Any] = field(default_factory=dict)


class AzureServiceBusBroker(InboundBroker):
    """`InboundBroker` backed by one Azure Service Bus queue."""

    def __init__(self, *, settings: AppSettings, queue: BrokerQueue) -> None:
        if ServiceBusClient is None:  # pragma: no cover - depends on deployment deps
            msg = "Install azure-servicebus to use BROKER_BACKEND=azure_servicebus"
            raise RuntimeError(msg)

        connection_string = settings.servicebus_connection_string.get_secret_value()
        if not connection_string:
            msg = "SERVICEBUS_CONNECTION_STRING is required for BROKER_BACKEND=azure_servicebus"
            raise RuntimeError(msg)

        self._queue = queue
        self._queue_name = settings.servicebus_queue_for(queue)
        self._client: Any = ServiceBusClient.from_connection_string(
            conn_str=connection_string,
            logging_enable=False,
        )
        # message_id (lock_token) -> shared handle. All messages from the
        # same accept-session call point at the same handle so we only close
        # the receiver once every sibling is ack-ed or nack-ed.
        self._handles: dict[str, _SessionHandle] = {}

    # ------------------------------------------------------------------
    # Producer
    # ------------------------------------------------------------------
    async def enqueue(self, *, partition_key: str, payload: dict[str, Any]) -> str:
        if ServiceBusMessage is None:  # pragma: no cover - depends on deployment deps
            msg = "Install azure-servicebus to use BROKER_BACKEND=azure_servicebus"
            raise BrokerEnqueueError(msg)

        message_id = str(payload.get("event_id") or uuid.uuid4())
        body = orjson.dumps(payload)
        message = ServiceBusMessage(
            body,
            message_id=message_id,
            session_id=partition_key,
            content_type="application/json",
            application_properties={
                "partition_key": partition_key,
                "queue": self._queue,
            },
        )
        try:
            async with self._client.get_queue_sender(queue_name=self._queue_name) as sender:
                await sender.send_messages(message)
        except Exception as exc:
            logger.error(
                "wabot.servicebus.enqueue_failed",
                queue=self._queue,
                queue_name=self._queue_name,
                partition_key=partition_key,
                error=str(exc),
            )
            msg = f"Failed to enqueue to Service Bus queue {self._queue_name!r}"
            raise BrokerEnqueueError(msg) from exc
        return message_id

    # ------------------------------------------------------------------
    # Consumer
    # ------------------------------------------------------------------
    async def ensure_consumer_group(self, *, group: str) -> None:
        # Service Bus topology is provisioned out-of-band (queue + session
        # support are created via Bicep / portal); there is no per-process
        # "create group" step the way Redis Streams has.
        del group

    async def consume(
        self,
        *,
        group: str,
        consumer: str,
        batch_size: int = 16,
        block_ms: int = 2000,
    ) -> list[InboundMessage]:
        del group, consumer
        if NEXT_AVAILABLE_SESSION is None:  # pragma: no cover - depends on deployment deps
            msg = "Install azure-servicebus to use BROKER_BACKEND=azure_servicebus"
            raise BrokerConsumeError(msg)

        # Service Bus expects seconds (float); never request less than one
        # second of wait time to avoid hammering the namespace on idle loops.
        max_wait = max(block_ms / 1000.0, 1.0)
        receiver = self._client.get_queue_receiver(
            queue_name=self._queue_name,
            session_id=NEXT_AVAILABLE_SESSION,
            max_wait_time=max_wait,
        )
        try:
            await receiver.__aenter__()
        except OperationTimeoutError:
            # No session became available within max_wait — the documented
            # idle signal. The worker loop will poll again immediately.
            return []
        except Exception as exc:
            logger.error(
                "wabot.servicebus.accept_session_failed",
                queue=self._queue,
                queue_name=self._queue_name,
                error=str(exc),
            )
            msg = f"Failed to accept Service Bus session on {self._queue_name!r}"
            raise BrokerConsumeError(msg) from exc

        try:
            received = await receiver.receive_messages(
                max_message_count=batch_size,
                max_wait_time=max_wait,
            )
        except OperationTimeoutError:
            # Session accepted but no messages arrived in the window. Release
            # the session so another worker (or this one's next poll) can
            # pick it up again.
            await _safe_aexit(receiver)
            return []
        except Exception as exc:
            await _safe_aexit(receiver)
            logger.error(
                "wabot.servicebus.consume_failed",
                queue=self._queue,
                queue_name=self._queue_name,
                error=str(exc),
            )
            msg = f"Failed to consume from Service Bus queue {self._queue_name!r}"
            raise BrokerConsumeError(msg) from exc

        if not received:
            await _safe_aexit(receiver)
            return []

        # Auto-renew the session lock so a slow handler does not lose it.
        renewer: Any | None = None
        if AutoLockRenewer is not None:
            try:
                renewer = AutoLockRenewer()
                renewer.register(
                    receiver,
                    receiver.session,
                    max_lock_renewal_duration=_SESSION_RENEW_SECONDS,
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "wabot.servicebus.lock_renewer_failed",
                    queue=self._queue,
                    queue_name=self._queue_name,
                    error=str(exc),
                )
                renewer = None

        handle = _SessionHandle(receiver=receiver, renewer=renewer)
        messages: list[InboundMessage] = []
        for raw in received:
            mid = str(raw.lock_token)
            handle.messages[mid] = raw
            self._handles[mid] = handle
            messages.append(_decode_message(mid, raw))
        logger.debug(
            "wabot.servicebus.session_batch",
            queue=self._queue,
            queue_name=self._queue_name,
            session_id=str(receiver.session.session_id),
            batch=len(messages),
        )
        return messages

    async def ack(self, *, message_id: str) -> None:
        await self._settle(message_id, settle="complete")

    async def nack(self, *, message_id: str) -> None:
        await self._settle(message_id, settle="abandon")

    async def close(self) -> None:
        # Dedupe shared handles by identity before closing so a session that
        # produced multiple messages is only torn down once.
        for handle in {id(h): h for h in self._handles.values()}.values():
            await _close_handle(handle, queue=self._queue, queue_name=self._queue_name)
        self._handles.clear()
        with suppress(Exception):
            await self._client.close()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _settle(self, message_id: str, *, settle: str) -> None:
        handle = self._handles.pop(message_id, None)
        if handle is None:
            logger.warning(
                "wabot.servicebus.settle_missing_inflight",
                queue=self._queue,
                queue_name=self._queue_name,
                message_id=message_id,
                settle=settle,
            )
            return
        message = handle.messages.pop(message_id, None)
        if message is not None:
            try:
                if settle == "complete":
                    await handle.receiver.complete_message(message)
                else:
                    await handle.receiver.abandon_message(message)
            except SessionLockLostError as exc:
                # The session lock expired while we held the message. The
                # broker will redeliver it; do not raise into the worker
                # loop — just log so the operator notices the trend.
                logger.warning(
                    "wabot.servicebus.session_lock_lost",
                    queue=self._queue,
                    queue_name=self._queue_name,
                    message_id=message_id,
                    settle=settle,
                    error=str(exc),
                )
            except Exception as exc:
                logger.warning(
                    "wabot.servicebus.settle_failed",
                    queue=self._queue,
                    queue_name=self._queue_name,
                    message_id=message_id,
                    settle=settle,
                    error=str(exc),
                )

        if not handle.messages:
            await _close_handle(handle, queue=self._queue, queue_name=self._queue_name)


async def _safe_aexit(receiver: Any) -> None:
    with suppress(Exception):
        await receiver.__aexit__(None, None, None)


async def _close_handle(handle: _SessionHandle, *, queue: str, queue_name: str) -> None:
    if handle.renewer is not None:
        with suppress(Exception):
            await handle.renewer.close()
    try:
        await handle.receiver.__aexit__(None, None, None)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "wabot.servicebus.receiver_close_failed",
            queue=queue,
            queue_name=queue_name,
            error=str(exc),
        )


def _decode_message(message_id: str, message: Any) -> InboundMessage:
    raw_body = b"".join(bytes(section) for section in message.body)
    try:
        payload = orjson.loads(raw_body)
    except orjson.JSONDecodeError as exc:
        logger.error(
            "wabot.servicebus.payload_decode_failed",
            message_id=message_id,
            error=str(exc),
        )
        msg = "Failed to decode Service Bus payload"
        raise BrokerConsumeError(msg) from exc
    if not isinstance(payload, dict):
        msg = f"Service Bus payload was not a JSON object: {type(payload).__name__}"
        raise BrokerConsumeError(msg)
    partition_key = str(message.session_id or payload.get("full_phone_number") or "")
    return InboundMessage(message_id=message_id, partition_key=partition_key, payload=payload)
