"""Outbound status worker.

Consumes the status webhook queue and runs the orchestrator's status
branch. Status events update `outbound_message`; they do not emit new
outbound messages, so this worker does not need an outbound pipeline.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
from contextlib import suppress
from typing import NoReturn

from wabot.adapters.broker import close_broker, get_broker
from wabot.cache import close_redis, get_redis
from wabot.data.db import dispose_engine, get_engine
from wabot.infra.config import AppSettings, get_settings
from wabot.infra.logging import configure_logging, get_logger
from wabot.infra.metrics import inc
from wabot.infra.telemetry import configure_telemetry
from wabot.services.orchestrator import Orchestrator

logger = get_logger(__name__)


def _consumer_name(settings: AppSettings) -> str:
    del settings
    return f"{socket.gethostname()}-status-{os.getpid()}"


async def _consume_forever(
    *,
    settings: AppSettings,
    orchestrator: Orchestrator,
    stop: asyncio.Event,
) -> None:
    broker = get_broker(settings, queue="status")
    group = settings.broker_status_group
    consumer = _consumer_name(settings)
    await broker.ensure_consumer_group(group=group)

    logger.info(
        "wabot.status_worker.consume_loop_start",
        queue="status",
        group=group,
        consumer=consumer,
    )

    while not stop.is_set():
        try:
            messages = await broker.consume(
                group=group,
                consumer=consumer,
                batch_size=32,
                block_ms=2000,
            )
        except Exception as exc:
            logger.error("wabot.status_worker.consume_failed", error=str(exc))
            await asyncio.sleep(1.0)
            continue

        for message in messages:
            if stop.is_set():
                break
            ok = await orchestrator.handle_message(message)
            if ok:
                await broker.ack(message_id=message.message_id)
                inc("wabot_worker_messages_total", labels={"queue": "status", "outcome": "acked"})
            else:
                await broker.nack(message_id=message.message_id)
                inc("wabot_worker_messages_total", labels={"queue": "status", "outcome": "retry"})


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings)
    configure_telemetry(settings)
    get_engine(settings)
    get_redis(settings)
    orchestrator = Orchestrator(settings)
    logger.info(
        "wabot.status_worker.start",
        broker=settings.broker_backend,
        env=settings.env,
    )
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    consume_task = asyncio.create_task(
        _consume_forever(settings=settings, orchestrator=orchestrator, stop=stop),
        name="wabot-status-consume",
    )
    try:
        await stop.wait()
    finally:
        consume_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await consume_task
        await close_broker()
        await close_redis()
        await dispose_engine()
        logger.info("wabot.status_worker.stop")


def main() -> NoReturn:
    with suppress(KeyboardInterrupt):  # pragma: no cover
        asyncio.run(_run())
    raise SystemExit(0)


if __name__ == "__main__":
    main()
