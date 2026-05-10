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

from typing import Any, Protocol, runtime_checkable


class BrokerEnqueueError(RuntimeError):
    """Raised when the broker cannot accept the message."""


@runtime_checkable
class InboundBroker(Protocol):
    """Append a single inbound event to the broker."""

    async def enqueue(
        self,
        *,
        partition_key: str,
        payload: dict[str, Any],
    ) -> str:
        """Append `payload` and return the broker-assigned id (e.g. stream entry id)."""

    async def close(self) -> None:
        """Release resources held by the broker (idempotent)."""
