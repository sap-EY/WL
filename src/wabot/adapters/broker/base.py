"""Broker port (typing.Protocol).

A broker is the pipe between the webhook ingress and the orchestrator
worker. Per-user FIFO is enforced by the broker via a stable
partitioning key — for Redis Streams we encode it inside the entry
payload and route consumers via consumer-group claim ordering; for
Azure Service Bus it becomes the message session id.

Concrete implementations live alongside this module
(`redis_streams.py`, etc.) and are wired through `factory.get_broker()`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

BrokerQueue = Literal["inbound", "status", "genai", "outbound"]
"""Logical queue names used by both Redis Streams and Azure Service Bus."""


class BrokerEnqueueError(RuntimeError):
    """Raised when the broker cannot accept the message."""


class BrokerConsumeError(RuntimeError):
    """Raised when the broker cannot deliver pending messages."""


@dataclass(frozen=True)
class InboundMessage:
    """Single broker entry handed to the orchestrator.

    `message_id` is broker-native (e.g. a Redis Streams `XADD` id) and
    must be passed back via `ack` once the orchestrator has durably
    advanced state for the contained event. `partition_key` is the
    same value the producer set; we keep it explicit so observability
    can attribute end-to-end latency by user.
    """

    message_id: str
    partition_key: str
    payload: dict[str, Any]


@runtime_checkable
class InboundBroker(Protocol):
    """Producer + consumer surface for the inbound user-events queue."""

    # ---- producer side -----------------------------------------------------

    async def enqueue(
        self,
        *,
        partition_key: str,
        payload: dict[str, Any],
    ) -> str:
        """Append `payload` and return the broker-assigned id."""

    # ---- consumer side -----------------------------------------------------

    async def ensure_consumer_group(self, *, group: str) -> None:
        """Create the consumer group if it does not exist (idempotent).

        Implementations must tolerate a pre-existing group without
        raising. Service Bus implementations may make this a no-op
        because subscription topology is provisioned out-of-band.
        """

    async def consume(
        self,
        *,
        group: str,
        consumer: str,
        batch_size: int = 16,
        block_ms: int = 2000,
    ) -> list[InboundMessage]:
        """Block up to `block_ms` for new messages; return up to `batch_size`.

        An empty list means the broker had nothing to deliver in the
        window — callers should loop. Implementations must NOT raise
        on idle timeout.
        """

    async def ack(self, *, message_id: str) -> None:
        """Acknowledge `message_id`; the broker may purge it from the queue."""

    async def nack(self, *, message_id: str) -> None:
        """Release `message_id` for retry without marking it processed."""

    async def close(self) -> None:
        """Release resources held by the broker (idempotent)."""
