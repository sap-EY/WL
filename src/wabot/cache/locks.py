"""Per-user Redis lock for the inbound orchestrator.

A doctor sending `text → button → text` quickly must have those events
processed serially: state-machine transitions are not commutative.
The broker partitions per phone number for FIFO, but with multiple
worker replicas a session rebalance could in theory deliver two events
for the same user concurrently. This lock is the **defensive second
layer** (see implementation_plan.md §11.1 / §11.2).

Mechanics:

* `SET key token NX PX ttl_ms` - atomic acquire.
* Watchdog task refreshes the TTL every `refresh_interval_seconds`
  while the handler is running so a long GenAI call (5-15 s) never
  loses the lock mid-flight.
* Release uses a Lua check-and-delete so we never delete someone
  else's token if our refresh failed silently and the lock expired.
"""

from __future__ import annotations

import asyncio
import secrets
from contextlib import suppress
from typing import TYPE_CHECKING

from wabot.infra.logging import get_logger

if TYPE_CHECKING:
    from types import TracebackType

    from redis.asyncio import Redis

logger = get_logger(__name__)


_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
""".strip()


_LOCK_KEY_PREFIX = "wabot:lock:user:"


def build_user_lock_key(full_phone_number: str) -> str:
    """Return the canonical Redis key for a per-user lock."""
    return f"{_LOCK_KEY_PREFIX}{full_phone_number}"


class UserLockUnavailableError(RuntimeError):
    """Raised when the lock could not be acquired before the deadline."""


class UserLock:
    """Async context manager wrapping `SET NX PX` with a refresh watchdog.

    Usage::

        async with UserLock(redis, full_phone_number="9170..."):
            ...  # journey handling

    Acquiring blocks (with `poll_interval_seconds` polling) until the
    lock is available or `acquire_timeout_seconds` elapses, in which
    case `UserLockUnavailableError` is raised. The caller (the worker)
    should treat that as a transient failure and not ack the broker
    message, so the consumer-group machinery redelivers it.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        full_phone_number: str,
        ttl_seconds: int = 30,
        refresh_interval_seconds: float = 10.0,
        acquire_timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.2,
    ) -> None:
        if ttl_seconds <= 0:
            msg = "ttl_seconds must be positive"
            raise ValueError(msg)
        if refresh_interval_seconds >= ttl_seconds:
            msg = "refresh_interval_seconds must be less than ttl_seconds"
            raise ValueError(msg)
        self._redis = redis
        self._full_phone_number = full_phone_number
        self._key = build_user_lock_key(full_phone_number)
        self._token = secrets.token_hex(16).encode("ascii")
        self._ttl_ms = ttl_seconds * 1000
        self._refresh = refresh_interval_seconds
        self._acquire_timeout = acquire_timeout_seconds
        self._poll = poll_interval_seconds
        self._watchdog: asyncio.Task[None] | None = None
        self._released = asyncio.Event()
        self._acquired = False

    async def __aenter__(self) -> UserLock:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._acquire_timeout
        while True:
            ok = await self._redis.set(
                name=self._key,
                value=self._token,
                nx=True,
                px=self._ttl_ms,
            )
            if ok:
                break
            if loop.time() >= deadline:
                logger.warning(
                    "wabot.lock.acquire_timeout",
                    key=self._key,
                    full_phone_number=self._full_phone_number,
                )
                msg = f"User lock unavailable: {self._full_phone_number}"
                raise UserLockUnavailableError(msg)
            await asyncio.sleep(self._poll)
        self._acquired = True
        self._watchdog = asyncio.create_task(
            self._refresh_loop(), name=f"user-lock-watchdog:{self._full_phone_number}"
        )
        logger.debug(
            "wabot.lock.acquired",
            key=self._key,
            full_phone_number=self._full_phone_number,
            ttl_ms=self._ttl_ms,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if not self._acquired:
            return
        self._released.set()
        if self._watchdog is not None:
            self._watchdog.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._watchdog
        try:
            await self._redis.eval(_RELEASE_SCRIPT, 1, self._key, self._token)
        except Exception as release_exc:
            logger.warning(
                "wabot.lock.release_failed",
                key=self._key,
                full_phone_number=self._full_phone_number,
                error=str(release_exc),
            )

    async def _refresh_loop(self) -> None:
        while not self._released.is_set():
            try:
                await asyncio.wait_for(self._released.wait(), timeout=self._refresh)
                return
            except TimeoutError:
                pass
            try:
                ok = await self._redis.pexpire(self._key, self._ttl_ms)
            except Exception as exc:
                logger.warning(
                    "wabot.lock.refresh_failed",
                    key=self._key,
                    full_phone_number=self._full_phone_number,
                    error=str(exc),
                )
                return
            if not ok:
                # Key gone (TTL elapsed): another worker may have taken it.
                # Stop refreshing — the handler should detect via DB
                # version conflict on commit (implementation_plan.md §11.7).
                logger.warning(
                    "wabot.lock.lost",
                    key=self._key,
                    full_phone_number=self._full_phone_number,
                )
                return
