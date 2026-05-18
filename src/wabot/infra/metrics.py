"""Small Prometheus-compatible metrics registry.

The project can swap this for `prometheus-client` later, but this
module keeps Phase 11 dependency-light while still exposing scrapeable
counters for the webhook, queue, worker, and status paths.
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock

LabelSet = tuple[tuple[str, str], ...]


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: defaultdict[str, dict[LabelSet, float]] = defaultdict(dict)

    def inc(self, name: str, *, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
        label_set = _normalise_labels(labels)
        with self._lock:
            self._counters[name][label_set] = self._counters[name].get(label_set, 0.0) + value

    def render(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name in sorted(self._counters):
                lines.append(f"# TYPE {name} counter")
                for labels, value in sorted(self._counters[name].items()):
                    suffix = _format_labels(labels)
                    rendered = int(value) if value.is_integer() else value
                    lines.append(f"{name}{suffix} {rendered}")
        lines.append("")
        return "\n".join(lines)


registry = MetricsRegistry()


def inc(name: str, *, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
    registry.inc(name, labels=labels, value=value)


def render_metrics() -> str:
    return registry.render()


def _normalise_labels(labels: dict[str, str] | None) -> LabelSet:
    if not labels:
        return ()
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


def _format_labels(labels: LabelSet) -> str:
    if not labels:
        return ""
    body = ",".join(f'{key}="{_escape_label(value)}"' for key, value in labels)
    return "{" + body + "}"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


__all__ = ["inc", "registry", "render_metrics"]
