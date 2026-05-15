"""Tests for `wabot.domain.parsers.registration` (Phase 7 \u2014 form flow)."""

from __future__ import annotations

import pytest

from wabot.domain.parsers.registration import (
    ParsedRegistration,
    RegistrationParseError,
    parse_form_response,
)

# Interakt prefixes form field keys with ``screen_<n>_``; the parser
# must match by case-insensitive substring.
_HAPPY_PAYLOAD: dict[str, object] = {
    "screen_0_first_name_0": "Jane",
    "screen_0_last_name_1": "Doe",
    "screen_0_mci_id_2": "MCI-12345",
    "screen_1_speciality_0": ["Cardiology", "Internal Medicine"],
}


def test_happy_path() -> None:
    parsed = parse_form_response(_HAPPY_PAYLOAD)
    assert isinstance(parsed, ParsedRegistration)
    assert parsed.first_name == "Jane"
    assert parsed.last_name == "Doe"
    assert parsed.mci_id == "MCI-12345"
    assert parsed.speciality == "Cardiology, Internal Medicine"


def test_speciality_as_comma_string() -> None:
    payload = {**_HAPPY_PAYLOAD, "screen_1_speciality_0": "Cardiology, Neurology"}
    parsed = parse_form_response(payload)
    assert parsed.speciality == "Cardiology, Neurology"


def test_speciality_single_string() -> None:
    payload = {**_HAPPY_PAYLOAD, "screen_1_speciality_0": "Cardiology"}
    parsed = parse_form_response(payload)
    assert parsed.speciality == "Cardiology"


def test_mci_id_is_optional() -> None:
    payload = {k: v for k, v in _HAPPY_PAYLOAD.items() if "mci" not in k}
    parsed = parse_form_response(payload)
    assert parsed.mci_id is None


def test_mci_id_blank_string_is_none() -> None:
    payload = {**_HAPPY_PAYLOAD, "screen_0_mci_id_2": "   "}
    parsed = parse_form_response(payload)
    assert parsed.mci_id is None


def test_strips_whitespace() -> None:
    payload = {
        "screen_0_first_name_0": "  Jane  ",
        "screen_0_last_name_1": " Doe ",
        "screen_1_speciality_0": ["  Cardiology  "],
    }
    parsed = parse_form_response(payload)
    assert parsed.first_name == "Jane"
    assert parsed.last_name == "Doe"
    assert parsed.speciality == "Cardiology"


def test_keys_are_case_insensitive() -> None:
    payload = {
        "Screen_0_FirstName_0": "Jane",
        "screen_0_LastName_1": "Doe",
        "screen_1_Specialty_0": ["Cardiology"],
    }
    parsed = parse_form_response(payload)
    assert parsed.first_name == "Jane"
    assert parsed.last_name == "Doe"
    assert parsed.speciality == "Cardiology"


def test_missing_first_name_raises() -> None:
    payload = {k: v for k, v in _HAPPY_PAYLOAD.items() if "first" not in k}
    with pytest.raises(RegistrationParseError) as exc_info:
        parse_form_response(payload)
    assert exc_info.value.reason == "empty"
    assert exc_info.value.field == "first_name"


def test_missing_last_name_raises() -> None:
    payload = {k: v for k, v in _HAPPY_PAYLOAD.items() if "last" not in k}
    with pytest.raises(RegistrationParseError) as exc_info:
        parse_form_response(payload)
    assert exc_info.value.field == "last_name"


def test_missing_speciality_raises() -> None:
    payload = {k: v for k, v in _HAPPY_PAYLOAD.items() if "special" not in k}
    with pytest.raises(RegistrationParseError) as exc_info:
        parse_form_response(payload)
    assert exc_info.value.field == "speciality"


def test_empty_speciality_list_raises() -> None:
    payload = {**_HAPPY_PAYLOAD, "screen_1_speciality_0": []}
    with pytest.raises(RegistrationParseError) as exc_info:
        parse_form_response(payload)
    assert exc_info.value.field == "speciality"


def test_empty_payload_raises() -> None:
    with pytest.raises(RegistrationParseError) as exc_info:
        parse_form_response({})
    assert exc_info.value.reason == "empty_payload"


def test_none_payload_raises() -> None:
    with pytest.raises(RegistrationParseError) as exc_info:
        parse_form_response(None)
    assert exc_info.value.reason == "empty_payload"
