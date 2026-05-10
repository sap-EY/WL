"""Cache layer.

Centralised Redis client and small primitives (dedupe, locks) used by
the webhook hot path and the orchestrator. Everything is async-only and
reuses a single connection pool managed at process lifespan.
"""

from __future__ import annotations

from wabot.cache.client import close_redis, get_redis, redis_ping
from wabot.cache.dedupe import WebhookDedupe

__all__ = ["WebhookDedupe", "close_redis", "get_redis", "redis_ping"]
