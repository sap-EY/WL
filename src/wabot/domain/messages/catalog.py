"""Symbolic message catalog.

The user-facing copy and the button labels live here so that:

* Handlers reference messages by symbol (`MessageSymbol.MSG_*`),
  never by literal string. This keeps copy changes localised and
  free of journey-handler edits.
* Translations / variants (when we add them) plug into the same
  symbol \u2192 text mapping.
* The dispatcher's `idempotency_key` includes the symbol so the same
  intent emitted twice (e.g. retry after a transient broker failure)
  resolves to the *same* `outbound_message` row.

Phase 6 ships the symbol enum plus the few entries every other
phase will need (registration completion/support messages, the consent template, the
hotline template, the post-answer "satisfied" buttons). Phases 7\u20139
will expand this file as the journeys come online; the contract
stays stable.

This module is intentionally a **plain data module** \u2014 no DB,
no I/O, no logging.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wabot.domain.outbound import OutboundKindLiteral


class MessageSymbol(StrEnum):
    """Stable identifier for every outbound message we send."""

    # Registration journey -------------------------------------------------
    MSG_REG_COMPLETED = "MSG_REG_COMPLETED"
    MSG_REG_ASSISTED_SUPPORT = "MSG_REG_ASSISTED_SUPPORT"

    # Registered journey ---------------------------------------------------
    MSG_REGISTERED_CONSENT_ACK = "MSG_REGISTERED_CONSENT_ACK"
    MSG_REGISTERED_CONSENT_DECLINED = "MSG_REGISTERED_CONSENT_DECLINED"
    MSG_REGISTERED_ICEBREAKER = "MSG_REGISTERED_ICEBREAKER"
    MSG_REGISTERED_ACK_THINKING = "MSG_REGISTERED_ACK_THINKING"
    MSG_REGISTERED_ANSWER_TEXT = "MSG_REGISTERED_ANSWER_TEXT"
    MSG_REGISTERED_ANSWER_WITH_BUTTONS = "MSG_REGISTERED_ANSWER_WITH_BUTTONS"
    MSG_REGISTERED_FALLBACK_CHOOSE_OPTION = "MSG_REGISTERED_FALLBACK_CHOOSE_OPTION"
    MSG_REGISTERED_FALLBACK_GENAI_FAILED = "MSG_REGISTERED_FALLBACK_GENAI_FAILED"

    # Templates ------------------------------------------------------------
    TEMPLATE_DOCTOR_WELCOME_CONSENT = "TEMPLATE_DOCTOR_WELCOME_CONSENT"
    TEMPLATE_HOTLINE = "TEMPLATE_HOTLINE"
    TEMPLATE_USER_REGISTRATION = "TEMPLATE_USER_REGISTRATION"


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """Static metadata about a message symbol.

    `kind` is the `OutboundIntent.kind` the builder must produce.
    `text` is the literal English copy for TEXT / BUTTONS messages
    (None for TEMPLATE entries \u2014 templates carry their copy inside
    Interakt). `template_setting_attr` names the `AppSettings`
    attribute that resolves to the Interakt template code-name (so
    we can rename templates without touching code).
    """

    symbol: MessageSymbol
    kind: OutboundKindLiteral
    text: str | None = None
    template_setting_attr: str | None = None


# Literal copy is intentionally minimal at this phase \u2014 Phases 7/8 will
# refine the wording in lockstep with the parser/router branches that
# emit each prompt. Keeping the strings here (rather than inline in the
# handlers) means a copy change is a one-line PR.
CATALOG: dict[MessageSymbol, CatalogEntry] = {
    MessageSymbol.MSG_REG_COMPLETED: CatalogEntry(
        symbol=MessageSymbol.MSG_REG_COMPLETED,
        kind="TEXT",
        text=("Thank you, Doctor.\nYour registration has been completed successfully."),
    ),
    MessageSymbol.MSG_REG_ASSISTED_SUPPORT: CatalogEntry(
        symbol=MessageSymbol.MSG_REG_ASSISTED_SUPPORT,
        kind="TEXT",
        text=(
            "Sorry, we are still unable to process your details.\n"
            "Please contact our support team for assistance."
        ),
    ),
    MessageSymbol.MSG_REGISTERED_ICEBREAKER: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_ICEBREAKER,
        kind="BUTTONS",
        text=(
            "Thank you Doctor,\n"
            "You can now start asking your product or medical information queries "
            "here in chat, and I will assist you with the relevant information.\U0001f60a\n"
            "If you need immediate support, you may connect with hotline support.\U0001f4de"
        ),
    ),
    MessageSymbol.MSG_REGISTERED_CONSENT_ACK: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_CONSENT_ACK,
        kind="TEXT",
        text=("Thank you, Doctor.\nYour consent has been recorded successfully."),
    ),
    MessageSymbol.MSG_REGISTERED_CONSENT_DECLINED: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_CONSENT_DECLINED,
        kind="TEXT",
        text=(
            "Thank you, Doctor.\n"
            "We will not continue with support messages at this time.\n"
            "If you wish to connect with us later, please reach out to our support team."
        ),
    ),
    MessageSymbol.MSG_REGISTERED_ACK_THINKING: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_ACK_THINKING,
        kind="TEXT",
        text="Let me check that for you. Please wait a moment\u2026\u23f3",
    ),
    MessageSymbol.MSG_REGISTERED_ANSWER_TEXT: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_ANSWER_TEXT,
        kind="TEXT",
    ),
    MessageSymbol.MSG_REGISTERED_ANSWER_WITH_BUTTONS: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_ANSWER_WITH_BUTTONS,
        kind="BUTTONS",
    ),
    MessageSymbol.MSG_REGISTERED_FALLBACK_CHOOSE_OPTION: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_FALLBACK_CHOOSE_OPTION,
        kind="TEXT",
        text=(
            "Sorry, Doctor \u2014 I didn\u2019t catch that.\n"
            "Please choose one of the options given in the previous message."
        ),
    ),
    MessageSymbol.MSG_REGISTERED_FALLBACK_GENAI_FAILED: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_FALLBACK_GENAI_FAILED,
        kind="TEXT",
        text=(
            "Sorry, Doctor.\n"
            "I\u2019m unable to fetch the answer right now.\n"
            "Please try again after some time or contact our support team for "
            "immediate assistance."
        ),
    ),
    MessageSymbol.TEMPLATE_DOCTOR_WELCOME_CONSENT: CatalogEntry(
        symbol=MessageSymbol.TEMPLATE_DOCTOR_WELCOME_CONSENT,
        kind="TEMPLATE",
        template_setting_attr="template_doctor_welcome_consent",
    ),
    MessageSymbol.TEMPLATE_HOTLINE: CatalogEntry(
        symbol=MessageSymbol.TEMPLATE_HOTLINE,
        kind="TEMPLATE",
        template_setting_attr="template_hotline",
    ),
    MessageSymbol.TEMPLATE_USER_REGISTRATION: CatalogEntry(
        symbol=MessageSymbol.TEMPLATE_USER_REGISTRATION,
        kind="TEMPLATE",
        template_setting_attr="template_user_registration",
    ),
}


# Stable per-prompt button identifiers. WhatsApp echoes these back in
# the `reply.id` field of `message_received` events; the registered
# journey handler keys off them.
class ButtonId(StrEnum):
    REGISTERED_ICEBREAKER_CALL_HOTLINE = "REGISTERED_ICEBREAKER_CALL_HOTLINE"
    REGISTERED_ANSWER_SATISFIED = "REGISTERED_ANSWER_SATISFIED"
    REGISTERED_ANSWER_CALL_HOTLINE = "REGISTERED_ANSWER_CALL_HOTLINE"


def get_entry(symbol: MessageSymbol) -> CatalogEntry:
    """Return the catalog entry for `symbol` or raise `KeyError`."""
    return CATALOG[symbol]
