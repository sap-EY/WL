"""Pure parsers for inbound free-text payloads.

Parsers live in the domain layer so journey handlers can stay free of
regex/string-munging and tests can pin parsing behaviour without any
DB or transport scaffolding.
"""

from wabot.domain.parsers.registration import (
    REGISTRATION_FIELD_COUNT,
    REGISTRATION_FIELDS,
    ParsedRegistration,
    RegistrationParseError,
    parse_registration,
)

__all__ = [
    "REGISTRATION_FIELDS",
    "REGISTRATION_FIELD_COUNT",
    "ParsedRegistration",
    "RegistrationParseError",
    "parse_registration",
]
