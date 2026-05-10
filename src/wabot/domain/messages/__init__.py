"""Symbolic message catalog + pure builders.

The catalog is the single source of truth for user-facing copy and
template identifiers; the builders translate `(symbol, params)` into
the wire-shape-agnostic `OutboundIntent` consumed by the dispatcher.
"""

from wabot.domain.messages.builder import (
    MessageBuildError,
    build_buttons,
    build_template,
    build_text,
)
from wabot.domain.messages.catalog import (
    CATALOG,
    ButtonId,
    CatalogEntry,
    MessageSymbol,
    get_entry,
)

__all__ = [
    "CATALOG",
    "ButtonId",
    "CatalogEntry",
    "MessageBuildError",
    "MessageSymbol",
    "build_buttons",
    "build_template",
    "build_text",
    "get_entry",
]
