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
phase will need (registration prompts, the consent template, the
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
    MSG_REG_FULL_DETAILS_PROMPT = "MSG_REG_FULL_DETAILS_PROMPT"
    MSG_REG_RETRY_PROMPT = "MSG_REG_RETRY_PROMPT"
    MSG_REG_REMAINING_FIELDS_PROMPT = "MSG_REG_REMAINING_FIELDS_PROMPT"
    MSG_REG_PARTIAL_CONFIRM_PROMPT = "MSG_REG_PARTIAL_CONFIRM_PROMPT"
    MSG_REG_COMPLETED = "MSG_REG_COMPLETED"
    MSG_REG_ASSISTED_SUPPORT = "MSG_REG_ASSISTED_SUPPORT"

    # Registered journey ---------------------------------------------------
    MSG_REGISTERED_ICEBREAKER = "MSG_REGISTERED_ICEBREAKER"
    MSG_REGISTERED_ACK_THINKING = "MSG_REGISTERED_ACK_THINKING"
    MSG_REGISTERED_ANSWER_WITH_BUTTONS = "MSG_REGISTERED_ANSWER_WITH_BUTTONS"
    MSG_REGISTERED_FALLBACK_CHOOSE_OPTION = "MSG_REGISTERED_FALLBACK_CHOOSE_OPTION"
    MSG_REGISTERED_FALLBACK_GENAI_FAILED = "MSG_REGISTERED_FALLBACK_GENAI_FAILED"

    # Templates ------------------------------------------------------------
    TEMPLATE_DOCTOR_WELCOME_CONSENT = "TEMPLATE_DOCTOR_WELCOME_CONSENT"
    TEMPLATE_HOTLINE = "TEMPLATE_HOTLINE"


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
    MessageSymbol.MSG_REG_FULL_DETAILS_PROMPT: CatalogEntry(
        symbol=MessageSymbol.MSG_REG_FULL_DETAILS_PROMPT,
        kind="TEXT",
        text=(
            "Welcome! Please share your registration details in a single message, "
            "separated by '#', in this order:\n"
            "Full Name#Speciality#Address#Email#City#State#Pincode"
        ),
    ),
    MessageSymbol.MSG_REG_RETRY_PROMPT: CatalogEntry(
        symbol=MessageSymbol.MSG_REG_RETRY_PROMPT,
        kind="TEXT",
        text=(
            "Sorry, we couldn't read all your details. Please resend in this exact format, "
            "separated by '#':\nFull Name#Speciality#Address#Email#City#State#Pincode"
        ),
    ),
    MessageSymbol.MSG_REG_REMAINING_FIELDS_PROMPT: CatalogEntry(
        symbol=MessageSymbol.MSG_REG_REMAINING_FIELDS_PROMPT,
        kind="TEXT",
        text="Please share the remaining details to complete your registration.",
    ),
    MessageSymbol.MSG_REG_PARTIAL_CONFIRM_PROMPT: CatalogEntry(
        symbol=MessageSymbol.MSG_REG_PARTIAL_CONFIRM_PROMPT,
        kind="BUTTONS",
        text="We have partial details for you. Should we use what we have on file?",
    ),
    MessageSymbol.MSG_REG_COMPLETED: CatalogEntry(
        symbol=MessageSymbol.MSG_REG_COMPLETED,
        kind="TEXT",
        text="Thanks, your registration is complete.",
    ),
    MessageSymbol.MSG_REG_ASSISTED_SUPPORT: CatalogEntry(
        symbol=MessageSymbol.MSG_REG_ASSISTED_SUPPORT,
        kind="TEXT",
        text=("We're connecting you with a support agent for assisted registration. Please wait."),
    ),
    MessageSymbol.MSG_REGISTERED_ICEBREAKER: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_ICEBREAKER,
        kind="BUTTONS",
        text="Welcome aboard! How can we help you today?",
    ),
    MessageSymbol.MSG_REGISTERED_ACK_THINKING: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_ACK_THINKING,
        kind="TEXT",
        text="Got it \u2014 looking that up for you, please wait.",
    ),
    MessageSymbol.MSG_REGISTERED_ANSWER_WITH_BUTTONS: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_ANSWER_WITH_BUTTONS,
        kind="BUTTONS",
    ),
    MessageSymbol.MSG_REGISTERED_FALLBACK_CHOOSE_OPTION: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_FALLBACK_CHOOSE_OPTION,
        kind="TEXT",
        text="Please choose one of the options shown above.",
    ),
    MessageSymbol.MSG_REGISTERED_FALLBACK_GENAI_FAILED: CatalogEntry(
        symbol=MessageSymbol.MSG_REGISTERED_FALLBACK_GENAI_FAILED,
        kind="TEXT",
        text=(
            "We're having trouble answering right now. Please try again in a moment "
            "or tap the hotline option for live assistance."
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
}


# Stable per-prompt button identifiers. WhatsApp echoes these back in
# the `reply.id` field of `message_received` events; the registered
# journey handler keys off them.
class ButtonId(StrEnum):
    REG_PARTIAL_CONFIRM_YES = "REG_PARTIAL_CONFIRM_YES"
    REG_PARTIAL_CONFIRM_NO = "REG_PARTIAL_CONFIRM_NO"
    REGISTERED_ASK_QUESTION = "REGISTERED_ASK_QUESTION"
    REGISTERED_TALK_TO_HOTLINE = "REGISTERED_TALK_TO_HOTLINE"
    REGISTERED_ANSWER_SATISFIED = "REGISTERED_ANSWER_SATISFIED"
    REGISTERED_ANSWER_CALL_HOTLINE = "REGISTERED_ANSWER_CALL_HOTLINE"


def get_entry(symbol: MessageSymbol) -> CatalogEntry:
    """Return the catalog entry for `symbol` or raise `KeyError`."""
    return CATALOG[symbol]
