"""Redis Streams broker adapter.

Implements `InboundBroker` over a single Redis Stream:

* `enqueue` calls `XADD` with `MAXLEN ~` for a soft cap, encoding the
  caller-supplied `partition_key` into the entry so consumers can
  preserve per-user FIFO when they pull.
* `consume` uses `XREADGROUP ... BLOCK <ms>` against a consumer group
  (created on demand via `ensure_consumer_group`). Per-user FIFO is
  preserved by deploying a single consumer per group in v1; we will
  add hash-based consumer affinity (`hash(partition_key) mod N`)
  before scaling out (implementation_plan.md §10.3).
* `ack` calls `XACK`. Pending entries that never get acked because the
  worker crashed are picked up by `XAUTOCLAIM` in the deployment
  janitor (Phase 13).

The payload is serialised with `orjson` and stored under a single
``data`` field; the partition key is stored under ``key`` for fast
routing without re-deserialisation.

This adapter holds no state of its own; the underlying Redis client is
the singleton from `wabot.cache.client`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import orjson
from redis.exceptions import ResponseError

from wabot.adapters.broker.base import (
    BrokerConsumeError,
    BrokerEnqueueError,
    InboundBroker,
    InboundMessage,
)
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

    async def ensure_consumer_group(self, *, group: str) -> None:
        try:
            await self._client.xgroup_create(
                name=self._stream,
                groupname=group,
                id="$",
                mkstream=True,
            )
            logger.info(
                "wabot.broker.consumer_group_created",
                stream=self._stream,
                group=group,
            )
        except ResponseError as exc:
            # `BUSYGROUP Consumer Group name already exists` is the
            # expected idempotent path; anything else is fatal.
            if "BUSYGROUP" in str(exc):
                return
            logger.error(
                "wabot.broker.consumer_group_create_failed",
                stream=self._stream,
                group=group,
                error=str(exc),
            )
            msg = f"Failed to ensure consumer group {group!r} on {self._stream!r}"
            raise BrokerConsumeError(msg) from exc

    async def consume(
        self,
        *,
        group: str,
        consumer: str,
        batch_size: int = 16,
        block_ms: int = 2000,
    ) -> list[InboundMessage]:
        try:
            response = await self._client.xreadgroup(
                groupname=group,
                consumername=consumer,
                streams={self._stream: ">"},
                count=batch_size,
                block=block_ms,
            )
        except Exception as exc:
            logger.error(
                "wabot.broker.consume_failed",
                stream=self._stream,
                group=group,
                consumer=consumer,
                error=str(exc),
            )
            msg = f"Failed to read from stream {self._stream!r}"
            raise BrokerConsumeError(msg) from exc

        if not response:
            return []

        messages: list[InboundMessage] = []
        for _stream_name, entries in response:
            for entry_id, fields in entries:
                messages.append(_decode_entry(entry_id, fields))
        return messages

    async def ack(self, *, message_id: str) -> None:
        settings = get_settings()
        try:
            await self._client.xack(self._stream, settings.broker_inbound_group, message_id)
        except Exception as exc:
            # Failing to ack is recoverable (XPENDING + XAUTOCLAIM will
            # redeliver); log loudly and let the worker continue.
            logger.warning(
                "wabot.broker.ack_failed",
                stream=self._stream,
                group=settings.broker_inbound_group,
                message_id=message_id,
                error=str(exc),
            )

    async def close(self) -> None:
        # The Redis client is owned by `wabot.cache.client`; nothing to do here.
        return


def _decode_entry(entry_id: bytes | str, fields: dict[bytes, bytes]) -> InboundMessage:
    raw_key = fields.get(b"key", b"")
    raw_data = fields.get(b"data", b"{}")
    try:
        payload = orjson.loads(raw_data)
    except orjson.JSONDecodeError as exc:
        logger.error(
            "wabot.broker.payload_decode_failed",
            entry_id=entry_id,
            error=str(exc),
        )
        msg = "Failed to decode broker payload"
        raise BrokerConsumeError(msg) from exc
    if not isinstance(payload, dict):
        msg = f"Broker payload was not a JSON object: {type(payload).__name__}"
        raise BrokerConsumeError(msg)
    return InboundMessage(
        message_id=entry_id.decode("utf-8") if isinstance(entry_id, bytes) else str(entry_id),
        partition_key=raw_key.decode("utf-8") if isinstance(raw_key, bytes) else str(raw_key),
        payload=payload,
    )
