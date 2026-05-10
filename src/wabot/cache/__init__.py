"""Cache layer.

Centralised Redis client and small primitives (dedupe, locks) used by
the webhook hot path and the orchestrator. Everything is async-only and
reuses a single connection pool managed at process lifespan.
"""

from __future__ import annotations

from wabot.cache.client import close_redis, get_redis, redis_ping
from wabot.cache.dedupe import WebhookDedupe
from wabot.cache.locks import UserLock, UserLockUnavailableError, build_user_lock_key

__all__ = [
    "UserLock",
    "UserLockUnavailableError",
    "WebhookDedupe",
    "build_user_lock_key",
    "close_redis",
    "get_redis",
    "redis_ping",
]
