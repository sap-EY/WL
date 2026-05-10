"""Broker factory.

Selects the concrete `InboundBroker` implementation based on
`settings.broker_backend` and caches one instance per process. Tests
can substitute their own implementation with `set_broker(...)`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wabot.adapters.broker.redis_streams import RedisStreamsBroker
from wabot.infra.config import AppSettings, get_settings
from wabot.infra.logging import get_logger

if TYPE_CHECKING:
    from wabot.adapters.broker.base import InboundBroker

logger = get_logger(__name__)

_broker: InboundBroker | None = None


def get_broker(settings: AppSettings | None = None) -> InboundBroker:
    """Return the process-wide broker, creating it on first use."""
    global _broker  # noqa: PLW0603 - cached singleton
    if _broker is None:
        settings = settings or get_settings()
        backend = settings.broker_backend
        if backend == "redis_streams":
            _broker = RedisStreamsBroker()
        elif backend == "azure_servicebus":  # pragma: no cover - phase 13
            msg = "Azure Service Bus broker not implemented yet"
            raise NotImplementedError(msg)
        else:  # pragma: no cover - exhaustive
            msg = f"Unknown broker backend: {backend!r}"
            raise ValueError(msg)
        logger.info("wabot.broker.created", backend=backend)
    return _broker


def set_broker(broker: InboundBroker | None) -> None:
    """Override (or clear) the cached broker — intended for tests."""
    global _broker  # noqa: PLW0603 - cached singleton
    _broker = broker


async def close_broker() -> None:
    """Dispose the cached broker (idempotent)."""
    global _broker  # noqa: PLW0603 - cached singleton
    if _broker is not None:
        await _broker.close()
    _broker = None
