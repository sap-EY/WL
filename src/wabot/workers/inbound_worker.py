"""Inbound worker.

Phase 5: drains the inbound broker and runs each message through the
orchestrator. The process-level structure (signal handling, lifespan,
exit codes) defined in earlier phases is preserved verbatim.

Concurrency model (implementation_plan.md §10.3 / §11):

* A single worker process per replica owns one consumer-group reader
  on `BROKER_INBOUND_STREAM`. Per-user FIFO is preserved because
  events for the same `partition_key` end up in the same XREADGROUP
  delivery and we serialize them by acquiring the per-user Redis lock
  inside the orchestrator.
* Messages are processed sequentially per worker; we do **not** spawn
  per-message tasks in v1. Phase 13 introduces a hash-partitioned
  fan-out for higher throughput.
* Acks happen only when the orchestrator returns ``True``. Transient
  failures (lock contention, DB outage) leave the entry pending and
  the consumer-group machinery redelivers it on the next poll.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
from contextlib import suppress
from typing import NoReturn

from wabot.adapters.broker import close_broker, get_broker
from wabot.adapters.genai import FakeGenAIPort
from wabot.adapters.interakt import InteraktClient
from wabot.cache import close_redis, get_redis
from wabot.data.db import dispose_engine, get_engine
from wabot.domain.ports.genai import register_genai_port
from wabot.infra.config import AppSettings, get_settings
from wabot.infra.logging import configure_logging, get_logger
from wabot.infra.metrics import inc
from wabot.infra.telemetry import configure_telemetry
from wabot.services.orchestrator import Orchestrator
from wabot.services.outbound_pipeline import OutboundPipeline

logger = get_logger(__name__)


def _consumer_name(settings: AppSettings) -> str:
    """Stable identifier for this consumer instance.

    Combining hostname + PID gives us human-readable observability in
    `XPENDING` listings without needing external coordination.
    """
    del settings
    return f"{socket.gethostname()}-{os.getpid()}"


async def _consume_forever(
    *,
    settings: AppSettings,
    orchestrator: Orchestrator,
    stop: asyncio.Event,
) -> None:
    broker = get_broker(settings, queue="inbound")
    group = settings.broker_inbound_group
    consumer = _consumer_name(settings)
    await broker.ensure_consumer_group(group=group)

    logger.info(
        "wabot.worker.consume_loop_start",
        stream=settings.broker_inbound_stream,
        group=group,
        consumer=consumer,
    )

    while not stop.is_set():
        try:
            messages = await broker.consume(
                group=group,
                consumer=consumer,
                batch_size=16,
                block_ms=2000,
            )
        except Exception as exc:
            logger.error("wabot.worker.consume_failed", error=str(exc))
            await asyncio.sleep(1.0)
            continue

        for message in messages:
            if stop.is_set():
                break
            ok = await orchestrator.handle_message(message)
            if ok:
                await broker.ack(message_id=message.message_id)
                inc("wabot_worker_messages_total", labels={"queue": "inbound", "outcome": "acked"})
            else:
                await broker.nack(message_id=message.message_id)
                inc("wabot_worker_messages_total", labels={"queue": "inbound", "outcome": "retry"})


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings)
    configure_telemetry(settings)
    get_engine(settings)
    get_redis(settings)
    interakt_client = InteraktClient(settings)
    pipeline = OutboundPipeline(client=interakt_client)
    orchestrator = Orchestrator(settings, pipeline=pipeline)
    if settings.use_fake_genai:
        # Local shake-out only: register the in-process fake GenAI
        # port so the Registered journey free-text branches can be
        # exercised without a live GenAI backend. Phase 9 replaces
        # this with a real httpx adapter.
        register_genai_port(FakeGenAIPort())
        logger.warning("wabot.worker.fake_genai_enabled")
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

    consume_task = asyncio.create_task(
        _consume_forever(settings=settings, orchestrator=orchestrator, stop=stop),
        name="wabot-inbound-consume",
    )
    try:
        await stop.wait()
    finally:
        consume_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await consume_task
        with suppress(Exception):
            await interakt_client.aclose()
        await close_broker()
        await close_redis()
        await dispose_engine()
        logger.info("wabot.worker.stop")


def main() -> NoReturn:
    with suppress(KeyboardInterrupt):  # pragma: no cover
        asyncio.run(_run())
    raise SystemExit(0)


if __name__ == "__main__":
    main()
