"""Tests for the Redis Streams broker consume API.

We mock the underlying `redis.asyncio.Redis` client; correctness of
the actual Redis commands is the redis-py library's responsibility.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import orjson
import pytest
from redis.exceptions import ResponseError

from wabot.adapters.broker.base import BrokerConsumeError
from wabot.adapters.broker.redis_streams import RedisStreamsBroker


def _make_broker(client: Any, *, stream: str = "wabot.inbound") -> RedisStreamsBroker:
    return RedisStreamsBroker(client=client, stream=stream)


@pytest.mark.asyncio
async def test_ensure_consumer_group_creates_when_missing() -> None:
    client = MagicMock()
    client.xgroup_create = AsyncMock(return_value=True)
    broker = _make_broker(client)

    await broker.ensure_consumer_group(group="g1")

    client.xgroup_create.assert_awaited_once()
    kwargs = client.xgroup_create.await_args.kwargs
    assert kwargs["name"] == "wabot.inbound"
    assert kwargs["groupname"] == "g1"
    assert kwargs["mkstream"] is True


@pytest.mark.asyncio
async def test_ensure_consumer_group_tolerates_busygroup() -> None:
    client = MagicMock()
    client.xgroup_create = AsyncMock(side_effect=ResponseError("BUSYGROUP exists"))
    broker = _make_broker(client)
    # Must not raise.
    await broker.ensure_consumer_group(group="g1")


@pytest.mark.asyncio
async def test_ensure_consumer_group_raises_on_unexpected_error() -> None:
    client = MagicMock()
    client.xgroup_create = AsyncMock(side_effect=ResponseError("WRONGTYPE"))
    broker = _make_broker(client)
    with pytest.raises(BrokerConsumeError):
        await broker.ensure_consumer_group(group="g1")


@pytest.mark.asyncio
async def test_consume_returns_decoded_messages() -> None:
    payload = {"event_id": "id-1", "full_phone_number": "9170000000"}
    client = MagicMock()
    client.xreadgroup = AsyncMock(
        return_value=[
            (
                b"wabot.inbound",
                [
                    (
                        b"1700000000-0",
                        {b"key": b"9170000000", b"data": orjson.dumps(payload)},
                    )
                ],
            )
        ]
    )
    broker = _make_broker(client)
    messages = await broker.consume(group="g1", consumer="c1")
    assert len(messages) == 1
    msg = messages[0]
    assert msg.message_id == "1700000000-0"
    assert msg.partition_key == "9170000000"
    assert msg.payload == payload


@pytest.mark.asyncio
async def test_consume_returns_empty_list_on_idle() -> None:
    client = MagicMock()
    client.xreadgroup = AsyncMock(return_value=None)
    broker = _make_broker(client)
    messages = await broker.consume(group="g1", consumer="c1", block_ms=10)
    assert messages == []


@pytest.mark.asyncio
async def test_ack_calls_xack_with_settings_group() -> None:
    client = MagicMock()
    client.xack = AsyncMock(return_value=1)
    broker = _make_broker(client)
    await broker.ack(message_id="1700000000-0")
    client.xack.assert_awaited_once()
    args = client.xack.await_args.args
    assert args[0] == "wabot.inbound"
    assert args[2] == "1700000000-0"


@pytest.mark.asyncio
async def test_consume_raises_on_underlying_failure() -> None:
    client = MagicMock()
    client.xreadgroup = AsyncMock(side_effect=RuntimeError("connection lost"))
    broker = _make_broker(client)
    with pytest.raises(BrokerConsumeError):
        await broker.consume(group="g1", consumer="c1")


@pytest.mark.asyncio
async def test_consume_rejects_non_object_payload() -> None:
    client = MagicMock()
    client.xreadgroup = AsyncMock(
        return_value=[
            (
                b"wabot.inbound",
                [(b"1-0", {b"key": b"k", b"data": orjson.dumps([1, 2, 3])})],
            )
        ]
    )
    broker = _make_broker(client)
    with pytest.raises(BrokerConsumeError):
        await broker.consume(group="g1", consumer="c1")
