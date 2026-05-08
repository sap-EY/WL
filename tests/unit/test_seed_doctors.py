"""Tests for the seed-doctors CSV loader (parser only, no DB writes)."""

from __future__ import annotations

import pytest
from scripts.seed_doctors import _coerce_bool, _normalize_phone, _row_to_kwargs


def test_normalize_phone_strips_non_digits() -> None:
    assert _normalize_phone("+91 99999-99999") == "919999999999"


def test_normalize_phone_too_short_raises() -> None:
    with pytest.raises(ValueError, match="too short"):
        _normalize_phone("123")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("FALSE", False),
        ("1", True),
        ("0", False),
        ("yes", True),
        ("no", False),
        (None, False),
        ("", False),
    ],
)
def test_coerce_bool(value: str | None, expected: bool) -> None:
    assert _coerce_bool(value) is expected


def test_row_to_kwargs_strips_and_normalizes() -> None:
    row = {
        "full_phone_number": " 91 99999 99999 ",
        "first_name": " Asha ",
        "last_name": "Rao",
        "speciality": "Cardiology",
        "email": "asha@example.com",
        "address": "  ",
        "city": "Mumbai",
        "state": "MH",
        "pincode": "400001",
        "is_profile_complete": "true",
    }
    out = _row_to_kwargs(row)
    assert out["full_phone_number"] == "919999999999"
    assert out["first_name"] == "Asha"
    assert out["address"] is None
    assert out["is_profile_complete"] is True
