"""Structured logging configuration.

structlog is the application logger; stdlib `logging` is configured to share
the same level so library logs (uvicorn, sqlalchemy) interleave consistently.

Behavior is driven entirely by `AppSettings`:
- `APP_LOG_LEVEL` — DEBUG / INFO / WARNING / ERROR
- `APP_LOG_JSON`  — when true (prod-like), emit JSON; otherwise human console

Every log record carries:
- `ts`    — UTC ISO-8601 with microsecond precision
- `level`
- `event` — the message
- `app`, `env`, `version` — bound globally at startup
- correlation-scoped fields (e.g. `correlation_id`, `path`, `method`) — bound
  per-request by `correlation.CorrelationMiddleware`.

Call `configure_logging()` exactly once per process (API and worker each call
it from their own startup path).
"""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any, cast

import orjson
import structlog

from wabot import __version__
from wabot.infra.config import AppSettings, get_settings

if TYPE_CHECKING:
    from structlog.types import EventDict, Processor

_CONFIGURED = False


def _orjson_serializer(event_dict: Any, default: Any = None, **_: Any) -> str:
    return orjson.dumps(event_dict, default=default).decode("utf-8")


def _drop_color_message_key(_: Any, __: str, event_dict: EventDict) -> EventDict:
    """Remove uvicorn's `color_message` duplicate of `event` from JSON output."""
    event_dict.pop("color_message", None)
    return event_dict


def _build_processors(*, json_logs: bool) -> list[Processor]:
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        _drop_color_message_key,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]
    if json_logs:
        shared.append(structlog.processors.JSONRenderer(serializer=_orjson_serializer))
    else:
        shared.append(structlog.dev.ConsoleRenderer(colors=True, sort_keys=False))
    return shared


def configure_logging(settings: AppSettings | None = None) -> None:
    """Initialize structlog + stdlib logging. Idempotent and safe to re-call."""
    global _CONFIGURED  # noqa: PLW0603 - module-level idempotency flag
    settings = settings or get_settings()
    level = logging.getLevelNamesMapping().get(settings.log_level.upper(), logging.INFO)

    processors = _build_processors(json_logs=settings.log_json)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Bind global metadata (always present on every record).
    structlog.contextvars.bind_contextvars(
        app=settings.name,
        env=settings.env,
        version=__version__,
    )

    # Route stdlib logs through plain handler at the same level so library
    # logs (uvicorn, sqlalchemy) appear with consistent severity. We do not
    # bridge them through structlog processors to avoid double-formatting; a
    # later phase can switch to ProcessorFormatter if uniform shape is needed.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Tame chatty libraries.
    for noisy in ("uvicorn.access", "asyncio"):
        logging.getLogger(noisy).setLevel(max(level, logging.INFO))

    _CONFIGURED = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger. Auto-configures on first use as a safety net."""
    if not _CONFIGURED:  # pragma: no cover - real callers configure explicitly
        configure_logging()
    logger = structlog.get_logger(name) if name else structlog.get_logger()
    return cast("structlog.stdlib.BoundLogger", logger)
