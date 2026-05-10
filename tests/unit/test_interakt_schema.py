"""Tests for the Pydantic Interakt webhook envelope.

These exercise the schema against the canonical sample payloads from
`interakt_webhook.md` so any future Interakt-side change forces an
update here as well.
"""

from __future__ import annotations

import pytest

from wabot.api.schemas.interakt_webhook import (
    EVENT_TYPE_API_CLICKED,
    EVENT_TYPE_API_SENT,
    EVENT_TYPE_RECEIVED,
    KNOWN_EVENT_TYPES,
    InteraktEnvelope,
)


def _envelope(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "version": "1.0",
        "timestamp": "2024-06-10T08:38:08.837610",
        "type": EVENT_TYPE_RECEIVED,
        "data": {
            "customer": {
                "channel_phone_number": "917003705584",
                "phone_number": "7003705584",
                "country_code": "+91",
            },
            "message": {
                "id": "abc-123",
                "message_status": "Sent",
                "is_template_message": False,
                "message_content_type": "Text",
                "message": "Hello",
                "meta_data": {},
            },
        },
    }
    base.update(overrides)
    return base


def test_envelope_extracts_routing_fields() -> None:
    env = InteraktEnvelope.model_validate(_envelope())
    assert env.type == EVENT_TYPE_RECEIVED
    assert env.interakt_message_id == "abc-123"
    assert env.message_status == "Sent"
    assert env.full_phone_number == "917003705584"


def test_envelope_falls_back_to_country_code_plus_phone() -> None:
    payload = _envelope()
    payload["data"]["customer"]["channel_phone_number"] = None  # type: ignore[index]
    env = InteraktEnvelope.model_validate(payload)
    assert env.full_phone_number == "917003705584"


def test_envelope_rejects_missing_type() -> None:
    payload = _envelope()
    del payload["type"]
    with pytest.raises(ValueError, match="type"):
        InteraktEnvelope.model_validate(payload)


def test_envelope_accepts_unknown_event_type_for_persistence() -> None:
    env = InteraktEnvelope.model_validate(_envelope(type="something_new"))
    assert env.type == "something_new"
    assert env.type not in KNOWN_EVENT_TYPES


def test_envelope_preserves_event_block_for_clicks() -> None:
    payload = _envelope(
        type=EVENT_TYPE_API_CLICKED,
        event={
            "callbackData": "out-id|corr-id",
            "click_type": "CTA",
            "button_text": "Track Order",
            "button_link": "https://example.com",
            "click_timestamp": "2024-06-10 08:47:26.948896",
        },
    )
    env = InteraktEnvelope.model_validate(payload)
    assert env.event is not None
    assert env.event.callbackData == "out-id|corr-id"
    assert env.event.button_text == "Track Order"


def test_envelope_keeps_unknown_extra_fields() -> None:
    payload = _envelope(type=EVENT_TYPE_API_SENT)
    payload["data"]["message"]["raw_template"] = "{...}"  # type: ignore[index]
    env = InteraktEnvelope.model_validate(payload)
    # Extra fields must be retained so the raw row is byte-faithful.
    dumped = env.model_dump()
    assert dumped["data"]["message"]["raw_template"] == "{...}"
