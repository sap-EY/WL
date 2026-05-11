"""Registration free-text parser (implementation_plan.md §Phase 7).

The parser is **pure** — no I/O, no DB, no settings. It consumes the
raw inbound text and returns a `ParsedRegistration` on success or
raises `RegistrationParseError` on any validation failure.

Contract (binding):

* Single inbound text split on ``#``. **Exactly 7 tokens** in this
  order: ``Full Name``, ``Speciality``, ``Address``, ``Email``,
  ``City``, ``State``, ``Pincode``.
* Each token is `.strip()`-ed before validation.
* ``Full Name`` is split once on the first whitespace run into
  ``first_name`` / ``last_name``. A single-word name keeps
  ``last_name = None``.
* Email must match a simple ``something@something.something`` regex
  (we do **not** try to be RFC-5322 compliant — Interakt itself does
  not deliver email so any reasonable shape is fine).
* Pincode must be exactly 6 digits (Indian postal codes).
* Any other token may not be empty after stripping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REGISTRATION_FIELD_COUNT = 7
"""Number of ``#``-separated tokens the parser requires."""

REGISTRATION_FIELDS: tuple[str, ...] = (
    "full_name",
    "speciality",
    "address",
    "email",
    "city",
    "state",
    "pincode",
)
"""Canonical field order (matches the prompt copy in
``MSG_REG_FULL_DETAILS_PROMPT``)."""

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PINCODE_RE = re.compile(r"^\d{6}$")


class RegistrationParseError(ValueError):
    """Raised when a registration payload fails validation.

    ``reason`` is a short machine-friendly slug (e.g.
    ``"field_count"``, ``"empty:speciality"``, ``"email_format"``).
    Handlers use it for logging / metrics; the user-facing copy lives
    in the catalog (``MSG_REG_RETRY_PROMPT``).
    """

    def __init__(self, reason: str, *, field: str | None = None) -> None:
        super().__init__(reason if field is None else f"{reason}:{field}")
        self.reason = reason
        self.field = field


@dataclass(frozen=True, slots=True)
class ParsedRegistration:
    """Validated registration payload ready for ``DoctorRepository.upsert_profile``."""

    first_name: str
    last_name: str | None
    speciality: str
    address: str
    email: str
    city: str
    state: str
    pincode: str


def parse_registration(text: str | None) -> ParsedRegistration:
    """Parse `text` into a `ParsedRegistration` or raise on any failure."""
    if text is None or not text.strip():
        raise RegistrationParseError("empty_payload")

    tokens = [token.strip() for token in text.split("#")]
    if len(tokens) != REGISTRATION_FIELD_COUNT:
        raise RegistrationParseError("field_count")

    full_name, speciality, address, email, city, state, pincode = tokens

    for value, field_name in zip(tokens, REGISTRATION_FIELDS, strict=True):
        if not value:
            raise RegistrationParseError("empty", field=field_name)

    if not _EMAIL_RE.match(email):
        raise RegistrationParseError("email_format", field="email")
    if not _PINCODE_RE.match(pincode):
        raise RegistrationParseError("pincode_format", field="pincode")

    first_name, last_name = _split_full_name(full_name)

    return ParsedRegistration(
        first_name=first_name,
        last_name=last_name,
        speciality=speciality,
        address=address,
        email=email,
        city=city,
        state=state,
        pincode=pincode,
    )


def _split_full_name(full_name: str) -> tuple[str, str | None]:
    """Split on the first whitespace run; return (first, last_or_none)."""
    parts = full_name.split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], None
    first, rest = parts
    rest = rest.strip()
    return first, (rest or None)
