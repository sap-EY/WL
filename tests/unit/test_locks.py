"""Tests for the per-user Redis lock.

These tests use a tiny in-memory `FakeRedis` that implements only the
operations `UserLock` actually calls (`set` with NX/PX, `pexpire`,
`eval` for the release Lua). That keeps the test hermetic and fast
without pulling in `fakeredis`.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from wabot.cache.locks import (
    UserLock,
    UserLockUnavailableError,
    build_user_lock_key,
)


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float | None]] = {}

    def _purge(self, now: float) -> None:
        expired = [
            k for k, (_, expires) in self._store.items() if expires is not None and expires <= now
        ]
        for key in expired:
            del self._store[key]

    async def set(
        self,
        *,
        name: str,
        value: Any,
        nx: bool = False,
        px: int | None = None,
        ex: int | None = None,
    ) -> bool | None:
        now = time.monotonic()
        self._purge(now)
        if nx and name in self._store:
            return None
        expires: float | None = None
        if px is not None:
            expires = now + px / 1000.0
        elif ex is not None:
            expires = now + ex
        self._store[name] = (value, expires)
        return True

    async def pexpire(self, name: str, ms: int) -> int:
        now = time.monotonic()
        self._purge(now)
        if name not in self._store:
            return 0
        value, _ = self._store[name]
        self._store[name] = (value, now + ms / 1000.0)
        return 1

    async def eval(self, script: str, num_keys: int, *args: Any) -> int:
        # Only the release script is exercised by UserLock.
        del num_keys, script
        key = args[0]
        token = args[1]
        self._purge(time.monotonic())
        if key in self._store and self._store[key][0] == token:
            del self._store[key]
            return 1
        return 0

    def _peek(self, key: str) -> Any | None:
        self._purge(time.monotonic())
        return self._store.get(key, (None, None))[0]


@pytest.mark.asyncio
async def test_lock_acquires_and_releases() -> None:
    redis = FakeRedis()
    key = build_user_lock_key("9170000000")
    async with UserLock(
        redis,  # type: ignore[arg-type]
        full_phone_number="9170000000",
        ttl_seconds=5,
        refresh_interval_seconds=1.0,
    ):
        assert redis._peek(key) is not None
    assert redis._peek(key) is None


@pytest.mark.asyncio
async def test_second_acquire_blocks_until_first_releases() -> None:
    redis = FakeRedis()

    async def first() -> None:
        async with UserLock(
            redis,  # type: ignore[arg-type]
            full_phone_number="9170000000",
            ttl_seconds=5,
            refresh_interval_seconds=1.0,
        ):
            await asyncio.sleep(0.1)

    async def second() -> float:
        await asyncio.sleep(0.02)  # let `first` grab it
        start = time.monotonic()
        async with UserLock(
            redis,  # type: ignore[arg-type]
            full_phone_number="9170000000",
            ttl_seconds=5,
            refresh_interval_seconds=1.0,
            acquire_timeout_seconds=2.0,
            poll_interval_seconds=0.02,
        ):
            return time.monotonic() - start

    _, waited = await asyncio.gather(first(), second())
    assert waited >= 0.05  # had to wait for first to release


@pytest.mark.asyncio
async def test_acquire_timeout_raises() -> None:
    redis = FakeRedis()
    key = build_user_lock_key("9170000000")
    # Pre-populate the key so acquire never succeeds within the deadline.
    await redis.set(name=key, value=b"someone-else", px=10_000)

    with pytest.raises(UserLockUnavailableError):
        async with UserLock(
            redis,  # type: ignore[arg-type]
            full_phone_number="9170000000",
            ttl_seconds=5,
            refresh_interval_seconds=1.0,
            acquire_timeout_seconds=0.1,
            poll_interval_seconds=0.02,
        ):
            pytest.fail("should not enter the lock")


@pytest.mark.asyncio
async def test_release_does_not_delete_other_owner_token() -> None:
    redis = FakeRedis()
    key = build_user_lock_key("9170000000")
    lock = UserLock(
        redis,  # type: ignore[arg-type]
        full_phone_number="9170000000",
        ttl_seconds=5,
        refresh_interval_seconds=1.0,
    )
    async with lock:
        # Simulate a TTL expiry + another worker grabbing the lock.
        redis._store[key] = (b"someone-else-token", None)
    # The release should have been a no-op since the token didn't match.
    assert redis._peek(key) == b"someone-else-token"


@pytest.mark.asyncio
async def test_invalid_intervals_rejected() -> None:
    redis = FakeRedis()
    with pytest.raises(ValueError):
        UserLock(
            redis,  # type: ignore[arg-type]
            full_phone_number="x",
            ttl_seconds=0,
        )
    with pytest.raises(ValueError):
        UserLock(
            redis,  # type: ignore[arg-type]
            full_phone_number="x",
            ttl_seconds=5,
            refresh_interval_seconds=10.0,
        )
