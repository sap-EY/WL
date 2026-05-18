"""Process-wide async Redis client.

A single `redis.asyncio.Redis` instance backed by a connection pool is
created on first use and closed during application shutdown. The
`ping()` helper is used by `/readyz` and never raises — failures are
logged and reported via the boolean return.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from redis.asyncio import Redis

from wabot.infra.config import AppSettings, get_settings
from wabot.infra.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable

logger = get_logger(__name__)

_client: Redis | None = None


def get_redis(settings: AppSettings | None = None) -> Redis:
    """Return the process-wide async Redis client, creating it on first use."""
    global _client  # noqa: PLW0603 - cached singleton
    if _client is None:
        settings = settings or get_settings()
        _client = Redis.from_url(
            settings.redis_url,
            decode_responses=False,
            socket_connect_timeout=2.0,
            socket_keepalive=True,
            health_check_interval=30,
        )
        logger.info("wabot.redis.client_created", url=_redacted_url(settings.redis_url))
    return _client


async def close_redis() -> None:
    """Dispose the Redis client (idempotent)."""
    global _client  # noqa: PLW0603 - cached singleton
    if _client is not None:
        await _client.aclose()
        logger.info("wabot.redis.client_closed")
    _client = None


async def redis_ping(timeout_seconds: float = 1.0) -> bool:
    """Cheap readiness probe; returns True iff `PING` succeeds within timeout."""
    client = get_redis()
    try:
        async with asyncio.timeout(timeout_seconds):
            await cast("Awaitable[bool]", client.ping())
        return True
    except Exception as exc:
        logger.warning("wabot.redis.ping_failed", error=str(exc))
        return False


def _redacted_url(url: str) -> str:
    if "@" not in url:
        return url
    scheme_creds, host = url.rsplit("@", 1)
    if "//" in scheme_creds:
        scheme, _ = scheme_creds.split("//", 1)
        return f"{scheme}//***@{host}"
    return f"***@{host}"
