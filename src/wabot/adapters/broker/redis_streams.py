"""Redis Streams broker adapter.

Implements `InboundBroker` over a single Redis Stream:

* `enqueue` calls `XADD` with `MAXLEN ~` for a soft cap, encoding the
  caller-supplied `partition_key` into the entry so consumers can
  preserve per-user FIFO when they pull (Phase 5 will add a hash-based
  consumer affinity, e.g. ``murmurhash(partition_key) % N``).
* The payload is serialised with `orjson` and stored under a single
  ``data`` field; the partition key is stored under ``key`` for fast
  routing without re-deserialisation.

This adapter holds no state of its own; the underlying Redis client is
the singleton from `wabot.cache.client`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import orjson

from wabot.adapters.broker.base import BrokerEnqueueError, InboundBroker
from wabot.cache.client import get_redis
from wabot.infra.config import get_settings
from wabot.infra.logging import get_logger

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = get_logger(__name__)

# ~10x our expected daily event volume — keeps the stream bounded under
# steady-state and prevents an unbounded-growth incident if the
# consumer falls behind catastrophically. The `~` makes Redis evict in
# O(1) on append.
_DEFAULT_MAXLEN = 100_000


class RedisStreamsBroker(InboundBroker):
    """`InboundBroker` backed by a single Redis Stream."""

    def __init__(
        self,
        *,
        client: Redis | None = None,
        stream: str | None = None,
        maxlen: int = _DEFAULT_MAXLEN,
    ) -> None:
        settings = get_settings()
        self._client = client or get_redis(settings)
        self._stream = stream or settings.broker_inbound_stream
        self._maxlen = maxlen

    async def enqueue(self, *, partition_key: str, payload: dict[str, Any]) -> str:
        try:
            entry_id = await self._client.xadd(
                name=self._stream,
                fields={
                    b"key": partition_key.encode("utf-8"),
                    b"data": orjson.dumps(payload),
                },
                maxlen=self._maxlen,
                approximate=True,
            )
        except Exception as exc:
            logger.error(
                "wabot.broker.enqueue_failed",
                stream=self._stream,
                partition_key=partition_key,
                error=str(exc),
            )
            msg = f"Failed to enqueue to stream {self._stream!r}"
            raise BrokerEnqueueError(msg) from exc
        return entry_id.decode("utf-8") if isinstance(entry_id, bytes) else str(entry_id)

    async def close(self) -> None:
        # The Redis client is owned by `wabot.cache.client`; nothing to do here.
        return
