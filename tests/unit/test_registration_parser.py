"""Tests for `wabot.domain.parsers.registration` (Phase 7)."""

from __future__ import annotations

import pytest

from wabot.domain.parsers.registration import (
    REGISTRATION_FIELD_COUNT,
    ParsedRegistration,
    RegistrationParseError,
    parse_registration,
)

_HAPPY_TEXT = "Jane Doe#Cardiology#221B Baker Street#jane.doe@example.com#Mumbai#Maharashtra#400001"


def test_parse_registration_happy_path() -> None:
    parsed = parse_registration(_HAPPY_TEXT)
    assert isinstance(parsed, ParsedRegistration)
    assert parsed.first_name == "Jane"
    assert parsed.last_name == "Doe"
    assert parsed.speciality == "Cardiology"
    assert parsed.address == "221B Baker Street"
    assert parsed.email == "jane.doe@example.com"
    assert parsed.city == "Mumbai"
    assert parsed.state == "Maharashtra"
    assert parsed.pincode == "400001"


def test_parse_registration_strips_whitespace() -> None:
    text = (
        "  Jane Doe  # Cardiology # 221B Baker Street # jane@example.com #"
        " Mumbai # Maharashtra # 400001  "
    )
    parsed = parse_registration(text)
    assert parsed.first_name == "Jane"
    assert parsed.last_name == "Doe"
    assert parsed.address == "221B Baker Street"


def test_parse_registration_single_word_full_name() -> None:
    text = "Madonna#Pop#Stage 7#m@example.com#London#London#400001"
    parsed = parse_registration(text)
    assert parsed.first_name == "Madonna"
    assert parsed.last_name is None


def test_parse_registration_three_word_full_name_keeps_remainder_as_last_name() -> None:
    text = "Mary Anne Smith#Pediatrics#Lane 1#mary@example.com#Delhi#Delhi#110001"
    parsed = parse_registration(text)
    assert parsed.first_name == "Mary"
    assert parsed.last_name == "Anne Smith"


def test_parse_registration_rejects_wrong_field_count() -> None:
    text = "Only#Three#Tokens"
    with pytest.raises(RegistrationParseError) as exc:
        parse_registration(text)
    assert exc.value.reason == "field_count"


def test_parse_registration_rejects_empty_field() -> None:
    text = "Jane Doe##221B#jane@example.com#Mumbai#MH#400001"
    with pytest.raises(RegistrationParseError) as exc:
        parse_registration(text)
    assert exc.value.reason == "empty"
    assert exc.value.field == "speciality"


def test_parse_registration_rejects_bad_email() -> None:
    text = "Jane Doe#Cardio#221B#not-an-email#Mumbai#MH#400001"
    with pytest.raises(RegistrationParseError) as exc:
        parse_registration(text)
    assert exc.value.reason == "email_format"


def test_parse_registration_rejects_bad_pincode() -> None:
    text = "Jane Doe#Cardio#221B#jane@example.com#Mumbai#MH#40001"  # 5 digits
    with pytest.raises(RegistrationParseError) as exc:
        parse_registration(text)
    assert exc.value.reason == "pincode_format"


def test_parse_registration_rejects_non_digit_pincode() -> None:
    text = "Jane Doe#Cardio#221B#jane@example.com#Mumbai#MH#4000A1"
    with pytest.raises(RegistrationParseError) as exc:
        parse_registration(text)
    assert exc.value.reason == "pincode_format"


def test_parse_registration_rejects_empty_text() -> None:
    with pytest.raises(RegistrationParseError) as exc:
        parse_registration("")
    assert exc.value.reason == "empty_payload"


def test_parse_registration_rejects_none() -> None:
    with pytest.raises(RegistrationParseError) as exc:
        parse_registration(None)
    assert exc.value.reason == "empty_payload"


def test_field_count_constant_matches_field_list() -> None:
    from wabot.domain.parsers.registration import REGISTRATION_FIELDS

    assert len(REGISTRATION_FIELDS) == REGISTRATION_FIELD_COUNT
