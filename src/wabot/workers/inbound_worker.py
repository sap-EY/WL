"""Inbound worker.

Phase 0 stub: starts up, logs identity, and idles cleanly. Phase 5 replaces the
body of `_run` with the real broker-consume → orchestrator pipeline. The
process-level structure (signal handling, lifespan, exit codes) defined here
is final.
"""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from typing import NoReturn

from wabot.infra.config import get_settings
from wabot.infra.logging import configure_logging, get_logger

logger = get_logger(__name__)


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings)
    logger.info(
        "wabot.worker.start",
        broker=settings.broker_backend,
        env=settings.env,
    )
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    # Phase 0: idle. Phase 5 will pull from the broker and dispatch.
    await stop.wait()
    logger.info("wabot.worker.stop")


def main() -> NoReturn:
    with suppress(KeyboardInterrupt):  # pragma: no cover
        asyncio.run(_run())
    raise SystemExit(0)


if __name__ == "__main__":
    main()
