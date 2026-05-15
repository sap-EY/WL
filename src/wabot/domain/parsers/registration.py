"""Registration form-response parser (implementation_plan.md §Phase 7).

The parser is **pure** — no I/O, no DB, no settings. It consumes the
`response_json` dict from a WhatsApp Flow `nfm_reply` submission and
returns a `ParsedRegistration` on success or raises
`RegistrationParseError` on any validation failure.

Form schema (configured inside Interakt, mirrored here):

* ``first_name`` — required text
* ``last_name``  — required text
* ``mci_id``     — optional text (Medical Council of India registration id)
* ``speciality`` — required multi-select (1+ options)
* ``Submit`` button

Interakt prefixes each form field key with ``screen_<n>_`` so the
parser matches keys by **case-insensitive substring** rather than
exact name. The screen layout is owned in Interakt and may change
without code edits.

Email / address / city / state / pincode are intentionally **NOT**
collected by the form. The journey handler stores ``None`` for those
columns so we can re-introduce them later without a DB migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class RegistrationParseError(ValueError):
    """Raised when a form response fails validation."""

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
    mci_id: str | None


# Field markers searched (case-insensitive) inside response_json keys.
_FIRST_NAME_MARKERS: tuple[str, ...] = ("first_name", "firstname", "fname")
_LAST_NAME_MARKERS: tuple[str, ...] = ("last_name", "lastname", "lname")
_MCI_ID_MARKERS: tuple[str, ...] = ("mci_id", "mciid", "mci")
_SPECIALITY_MARKERS: tuple[str, ...] = ("speciality", "specialty", "specialization")


def parse_form_response(response_json: dict[str, Any] | None) -> ParsedRegistration:
    """Parse a Flow `response_json` dict or raise on validation failure."""
    if not isinstance(response_json, dict) or not response_json:
        raise RegistrationParseError("empty_payload")

    first_name = _pick(response_json, _FIRST_NAME_MARKERS)
    last_name = _pick(response_json, _LAST_NAME_MARKERS)
    speciality_raw = _pick_raw(response_json, _SPECIALITY_MARKERS)
    mci_id = _pick(response_json, _MCI_ID_MARKERS)

    if not first_name:
        raise RegistrationParseError("empty", field="first_name")
    if not last_name:
        raise RegistrationParseError("empty", field="last_name")

    speciality = _normalise_speciality(speciality_raw)
    if not speciality:
        raise RegistrationParseError("empty", field="speciality")

    return ParsedRegistration(
        first_name=first_name,
        last_name=last_name,
        speciality=speciality,
        mci_id=mci_id or None,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pick(payload: dict[str, Any], markers: tuple[str, ...]) -> str | None:
    """Return the first value whose key contains any of `markers` as a
    case-insensitive substring. The matched value is stripped; an empty
    string returns ``None``."""
    value = _pick_raw(payload, markers)
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value).strip() or None


def _pick_raw(payload: dict[str, Any], markers: tuple[str, ...]) -> Any:
    for key, value in payload.items():
        if not isinstance(key, str):
            continue
        lower = key.lower()
        for marker in markers:
            if marker in lower:
                return value
    return None


def _normalise_speciality(value: Any) -> str | None:
    """Multi-select fields may arrive as a list, a single string, or a
    comma-separated string. Join into a clean ``", "`` joined string.
    """
    if value is None:
        return None
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",") if p.strip()]
    elif isinstance(value, (list, tuple)):
        parts = [str(p).strip() for p in value if str(p).strip()]
    else:
        parts = [str(value).strip()]
    return ", ".join(parts) or None


__all__ = [
    "ParsedRegistration",
    "RegistrationParseError",
    "parse_form_response",
]
