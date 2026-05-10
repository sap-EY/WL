"""Webhook short-TTL dedupe.

Interakt occasionally retries a webhook within seconds when its
internal client times out. The DB-side partial unique index on
`webhook_event_raw` is the strong guarantee, but this Redis-backed
pre-filter lets us short-circuit duplicate POSTs without a DB hit, so
the ack stays well under the 3 s contract even under bursts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wabot.cache.client import get_redis
from wabot.infra.config import get_settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

_KEY_PREFIX = "wabot:webhook:dedupe:"


def build_dedupe_key(
    *,
    event_type: str,
    interakt_message_id: str | None,
    message_status: str | None,
) -> str:
    """Compose the dedupe cache key.

    `(event_type, interakt_message_id, message_status)` mirrors the DB
    partial unique index. When `message_status` is missing (e.g. for
    `message_received`) we use the literal sentinel ``"-"`` so the key
    is still unique per logical event.
    """
    msg_id = interakt_message_id or "-"
    status = message_status or "-"
    return f"{_KEY_PREFIX}{event_type}:{msg_id}:{status}"


class WebhookDedupe:
    """Best-effort idempotency check using `SET NX EX`."""

    def __init__(self, client: Redis | None = None, ttl_seconds: int | None = None) -> None:
        self._client = client or get_redis()
        self._ttl = (
            ttl_seconds if ttl_seconds is not None else get_settings().redis_dedupe_ttl_seconds
        )

    async def claim(self, key: str) -> bool:
        """Try to claim `key` for processing. Returns True on first claim."""
        # SET NX EX returns True when the key was set, None when it already existed.
        result = await self._client.set(name=key, value=b"1", nx=True, ex=self._ttl)
        return bool(result)
