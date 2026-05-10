"""Broker adapters.

The webhook hot path enqueues to an `InboundBroker`; the orchestrator
worker (Phase 5) consumes from the same port. Two implementations are
planned: Redis Streams (local + small deployments) and Azure Service
Bus with sessions (cloud, per-user FIFO via session id).
"""

from __future__ import annotations

from wabot.adapters.broker.base import (
    BrokerConsumeError,
    BrokerEnqueueError,
    InboundBroker,
    InboundMessage,
)
from wabot.adapters.broker.factory import close_broker, get_broker

__all__ = [
    "BrokerConsumeError",
    "BrokerEnqueueError",
    "InboundBroker",
    "InboundMessage",
    "close_broker",
    "get_broker",
]
