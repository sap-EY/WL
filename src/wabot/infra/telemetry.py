"""Optional Azure Monitor / OpenTelemetry bootstrap."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from wabot.infra.logging import get_logger

try:  # pragma: no cover - import depends on deployment deps
    _azure_monitor = import_module("azure.monitor.opentelemetry")
except ImportError:  # pragma: no cover - local tests can run without Azure SDK
    configure_azure_monitor = None
else:  # pragma: no cover - exercised when Azure Monitor SDK is installed
    configure_azure_monitor = _azure_monitor.configure_azure_monitor

if TYPE_CHECKING:
    from wabot.infra.config import AppSettings

logger = get_logger(__name__)


def configure_telemetry(settings: AppSettings) -> None:
    """Configure Azure Monitor when explicitly enabled.

    Local development and unit tests keep `OTEL_ENABLED=false`, so this
    function is a no-op unless deployment env vars opt in.
    """
    if not settings.otel_enabled:
        return
    connection_string = settings.azure_monitor_connection_string.get_secret_value()
    if not connection_string:
        logger.warning("wabot.telemetry.azure_monitor_missing_connection_string")
        return
    if configure_azure_monitor is None:
        logger.warning("wabot.telemetry.azure_monitor_package_missing")
        return
    configure_azure_monitor(connection_string=connection_string)
    logger.info("wabot.telemetry.azure_monitor_configured")


__all__ = ["configure_telemetry"]
