"""Azure Service Bus broker adapter.

This implementation binds one adapter instance to one logical queue
(`inbound`, `status`, `genai`, or `outbound`). Messages use Service
Bus sessions with `session_id = full_phone_number` so each doctor's
sequence is FIFO while different doctors can process concurrently.
"""

from __future__ import annotations

import uuid
from contextlib import suppress
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

    ServiceBusReceiver = Any
    ServiceBusReceivedMessage = Any

logger = get_logger(__name__)

NEXT_AVAILABLE_SESSION: Any = None
ServiceBusClient: Any = None
ServiceBusMessage: Any = None

try:  # pragma: no cover - import depends on deployment deps
    _servicebus = import_module("azure.servicebus")
    _servicebus_aio = import_module("azure.servicebus.aio")
except ImportError:  # pragma: no cover - local tests can run without Azure SDK
    pass
else:  # pragma: no cover - exercised when Azure SDK is installed
    NEXT_AVAILABLE_SESSION = _servicebus.NEXT_AVAILABLE_SESSION
    ServiceBusClient = _servicebus_aio.ServiceBusClient
    ServiceBusMessage = _servicebus.ServiceBusMessage


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
        self._inflight: dict[str, tuple[ServiceBusReceiver, ServiceBusReceivedMessage]] = {}

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

    async def ensure_consumer_group(self, *, group: str) -> None:
        del group

    async def consume(
        self,
        *,
        group: str,
        consumer: str,
        batch_size: int = 16,
        block_ms: int = 2000,
    ) -> list[InboundMessage]:
        del group, consumer, batch_size
        if NEXT_AVAILABLE_SESSION is None:  # pragma: no cover - depends on deployment deps
            msg = "Install azure-servicebus to use BROKER_BACKEND=azure_servicebus"
            raise BrokerConsumeError(msg)
        try:
            receiver = self._client.get_queue_receiver(
                queue_name=self._queue_name,
                session_id=NEXT_AVAILABLE_SESSION,
                max_wait_time=block_ms / 1000,
            )
            await receiver.__aenter__()
        except TimeoutError:
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
                max_message_count=1,
                max_wait_time=block_ms / 1000,
            )
        except Exception as exc:
            await receiver.__aexit__(type(exc), exc, exc.__traceback__)
            logger.error(
                "wabot.servicebus.consume_failed",
                queue=self._queue,
                queue_name=self._queue_name,
                error=str(exc),
            )
            msg = f"Failed to consume from Service Bus queue {self._queue_name!r}"
            raise BrokerConsumeError(msg) from exc

        if not received:
            await receiver.__aexit__(None, None, None)
            return []

        messages: list[InboundMessage] = []
        for message in received:
            lock_token = str(message.lock_token)
            self._inflight[lock_token] = (receiver, message)
            messages.append(_decode_message(lock_token, message))
        return messages

    async def ack(self, *, message_id: str) -> None:
        inflight = self._inflight.pop(message_id, None)
        if inflight is None:
            logger.warning(
                "wabot.servicebus.ack_missing_inflight",
                queue=self._queue,
                queue_name=self._queue_name,
                message_id=message_id,
            )
            return
        receiver, message = inflight
        try:
            await receiver.complete_message(message)
        except Exception as exc:
            logger.warning(
                "wabot.servicebus.ack_failed",
                queue=self._queue,
                queue_name=self._queue_name,
                message_id=message_id,
                error=str(exc),
            )
        finally:
            await receiver.__aexit__(None, None, None)

    async def nack(self, *, message_id: str) -> None:
        inflight = self._inflight.pop(message_id, None)
        if inflight is None:
            logger.warning(
                "wabot.servicebus.nack_missing_inflight",
                queue=self._queue,
                queue_name=self._queue_name,
                message_id=message_id,
            )
            return
        receiver, message = inflight
        try:
            await receiver.abandon_message(message)
        except Exception as exc:
            logger.warning(
                "wabot.servicebus.nack_failed",
                queue=self._queue,
                queue_name=self._queue_name,
                message_id=message_id,
                error=str(exc),
            )
        finally:
            await receiver.__aexit__(None, None, None)

    async def close(self) -> None:
        for receiver, _message in list(self._inflight.values()):
            with suppress(Exception):
                await receiver.__aexit__(None, None, None)
        self._inflight.clear()
        await self._client.close()


def _decode_message(message_id: str, message: ServiceBusReceivedMessage) -> InboundMessage:
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
