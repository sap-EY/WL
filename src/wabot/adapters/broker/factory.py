"""Broker factory.

Selects the concrete `InboundBroker` implementation based on
`settings.broker_backend` and caches one instance per process. Tests
can substitute their own implementation with `set_broker(...)`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wabot.adapters.broker.azure_servicebus import AzureServiceBusBroker
from wabot.adapters.broker.redis_streams import RedisStreamsBroker
from wabot.infra.config import AppSettings, get_settings
from wabot.infra.logging import get_logger

if TYPE_CHECKING:
    from wabot.adapters.broker.base import BrokerQueue, InboundBroker

logger = get_logger(__name__)

_brokers: dict[BrokerQueue, InboundBroker] = {}


def get_broker(
    settings: AppSettings | None = None,
    *,
    queue: BrokerQueue = "inbound",
) -> InboundBroker:
    """Return the process-wide broker for `queue`, creating it on first use."""
    if queue not in _brokers:
        settings = settings or get_settings()
        backend = settings.broker_backend
        if backend == "redis_streams":
            _brokers[queue] = RedisStreamsBroker(queue=queue)
        elif backend == "azure_servicebus":  # pragma: no cover - exercised only with Azure SDK
            _brokers[queue] = AzureServiceBusBroker(settings=settings, queue=queue)
        else:  # pragma: no cover - exhaustive
            msg = f"Unknown broker backend: {backend!r}"
            raise ValueError(msg)
        logger.info("wabot.broker.created", backend=backend, queue=queue)
    return _brokers[queue]


def set_broker(broker: InboundBroker | None, *, queue: BrokerQueue = "inbound") -> None:
    """Override (or clear) the cached broker — intended for tests."""
    if broker is None:
        _brokers.pop(queue, None)
    else:
        _brokers[queue] = broker


async def close_broker() -> None:
    """Dispose all cached brokers (idempotent)."""
    for broker in list(_brokers.values()):
        await broker.close()
    _brokers.clear()
