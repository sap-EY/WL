"""Pure builders that turn a `(MessageSymbol, params)` pair into an
`OutboundIntent`.

These functions are deterministic, side-effect free, and do not look
up the doctor/journey state \u2014 they are just shape conversions. Tests
can call them with literal arguments to assert the wire shape.

The orchestrator owns settings (template names) so it passes them in
via `templates`. We keep the builder signatures explicit rather than
pulling settings into the domain layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wabot.domain.messages.catalog import (
    CATALOG,
    ButtonId,
    CatalogEntry,
    MessageSymbol,
    get_entry,
)
from wabot.domain.outbound import InteractiveButton, OutboundIntent

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class MessageBuildError(ValueError):
    """Raised when the catalog kind doesn't match the builder used."""


def build_text(
    *,
    symbol: MessageSymbol,
    full_phone_number: str,
    text_override: str | None = None,
) -> OutboundIntent:
    """Build a TEXT intent. `text_override` lets handlers inject
    GenAI-returned answer text while still going through the catalog.
    """
    entry = _entry_for(symbol, "TEXT")
    text = text_override if text_override is not None else entry.text
    if text is None:
        msg = f"Catalog entry {symbol} has no text and no override was provided"
        raise MessageBuildError(msg)
    return OutboundIntent(
        kind="TEXT",
        full_phone_number=full_phone_number,
        symbol=symbol.value,
        text=text,
    )


def build_buttons(
    *,
    symbol: MessageSymbol,
    full_phone_number: str,
    buttons: Sequence[tuple[ButtonId | str, str]],
    text_override: str | None = None,
) -> OutboundIntent:
    """Build an `InteractiveButton` intent.

    `buttons` is a sequence of `(button_id, title)` tuples. We accept
    either a `ButtonId` enum value or a raw string for the id so the
    GenAI answer flow can attach dynamic ids when needed.
    """
    entry = _entry_for(symbol, "BUTTONS")
    text = text_override if text_override is not None else entry.text
    if text is None:
        msg = f"Catalog entry {symbol} has no body text and no override was provided"
        raise MessageBuildError(msg)
    if not buttons:
        msg = f"build_buttons({symbol}) requires at least one button"
        raise MessageBuildError(msg)
    interactive = tuple(InteractiveButton(id=str(btn_id), title=title) for btn_id, title in buttons)
    return OutboundIntent(
        kind="BUTTONS",
        full_phone_number=full_phone_number,
        symbol=symbol.value,
        text=text,
        buttons=interactive,
    )


def build_template(
    *,
    symbol: MessageSymbol,
    full_phone_number: str,
    template_name: str,
    template_locale: str = "en",
    body_values: Sequence[str] | None = None,
    header_values: Sequence[str] | None = None,
    button_values: Mapping[str, Sequence[str]] | None = None,
    file_name: str | None = None,
) -> OutboundIntent:
    """Build a TEMPLATE intent.

    `template_name` is the Interakt code-name (resolved from settings
    by the caller \u2014 see `AppSettings.template_*`). The catalog entry
    only validates that the symbol *is* a template.
    """
    _entry_for(symbol, "TEMPLATE")
    return OutboundIntent(
        kind="TEMPLATE",
        full_phone_number=full_phone_number,
        symbol=symbol.value,
        template_name=template_name,
        template_locale=template_locale,
        body_values=tuple(body_values) if body_values is not None else None,
        header_values=tuple(header_values) if header_values is not None else None,
        button_values=(
            {k: tuple(v) for k, v in button_values.items()} if button_values is not None else None
        ),
        file_name=file_name,
    )


def _entry_for(symbol: MessageSymbol, expected_kind: str) -> CatalogEntry:
    entry = CATALOG.get(symbol)
    if entry is None:
        msg = f"Unknown catalog symbol: {symbol}"
        raise MessageBuildError(msg)
    if entry.kind != expected_kind:
        msg = (
            f"Catalog kind mismatch for {symbol}: builder expects {expected_kind}, "
            f"catalog declares {entry.kind}"
        )
        raise MessageBuildError(msg)
    return entry


__all__ = [
    "MessageBuildError",
    "build_buttons",
    "build_template",
    "build_text",
    "get_entry",
]
