"""Tests for `wabot.adapters.interakt.normalizer`.

The fixtures here are minimised but **structurally faithful** to
`interakt_webhook.md`. Each test asserts both the surface routing
fields (`event_kind`, `text`, `button_text`) and the cross-cutting
contracts (`callback_data` extraction across both click variants and
status events; `referenced_outbound_message_id` parsing).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from wabot.adapters.interakt.normalizer import (
    NormalizationError,
    UnsupportedEventTypeError,
    normalize,
)
from wabot.domain.events import EventKind

_RAW_EVENT_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
_CORRELATION_ID = "corr-abc"
_OUTBOUND_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
_CALLBACK = f"{_OUTBOUND_ID}|{_CORRELATION_ID}"


def _customer(**extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "cust-1",
        "channel_phone_number": "917003705584",
        "phone_number": "7003705584",
        "country_code": "+91",
    }
    base.update(extra)
    return base


def _do_normalize(payload: dict[str, Any]):
    return normalize(
        raw_event_id=_RAW_EVENT_ID,
        correlation_id=_CORRELATION_ID,
        payload=payload,
    )


def test_message_received_text() -> None:
    payload = {
        "version": "1.0",
        "timestamp": "2024-06-10T08:38:08.837610",
        "type": "message_received",
        "data": {
            "customer": _customer(),
            "message": {
                "id": "abc-text-1",
                "message_status": "Sent",
                "message_content_type": "Text",
                "message": "Hello there",
                "received_at_utc": "2024-06-10T08:37:50.123456",
                "meta_data": {},
            },
        },
    }
    event = _do_normalize(payload)
    assert event.event_kind is EventKind.USER_TEXT
    assert event.text == "Hello there"
    assert event.button_text is None
    assert event.full_phone_number == "917003705584"
    assert event.interakt_customer_id == "cust-1"
    assert event.received_at.isoformat() == "2024-06-10T08:37:50.123456+00:00"


def test_message_received_interactive_button_reply() -> None:
    payload = {
        "version": "1.0",
        "timestamp": "2024-06-10T08:38:08.837610",
        "type": "message_received",
        "data": {
            "customer": _customer(),
            "message": {
                "id": "abc-btn-1",
                "message_status": "Sent",
                "message_content_type": "Interactive",
                "message": "",
                "meta_data": {
                    "button_payload": {
                        "payload": {
                            "type": "QUICK_REPLY",
                            "text": "Yes, I consent",
                        }
                    }
                },
            },
        },
    }
    event = _do_normalize(payload)
    assert event.event_kind is EventKind.USER_BUTTON_REPLY
    assert event.button_text == "Yes, I consent"
    assert event.text is None


def test_message_api_clicked_quick_reply_variant() -> None:
    payload = {
        "version": "1.0",
        "timestamp": "2024-06-10T08:38:08.837610",
        "type": "message_api_clicked",
        "data": {
            "customer": _customer(),
            "message": {
                "id": "abc-qr-1",
                "message_status": "Read",
                "message_content_type": "Template",
                "meta_data": {
                    "source_data": {"callback_data": _CALLBACK},
                    "click_type": "QR",
                    "button_text": "Fill Feedback Form",
                    "button_payload": {
                        "payload": {"type": "QUICK_REPLY", "text": "Fill Feedback Form"}
                    },
                },
            },
        },
    }
    event = _do_normalize(payload)
    assert event.event_kind is EventKind.OUTBOUND_CLICKED
    assert event.click_type == "QR"
    assert event.button_text == "Fill Feedback Form"
    assert event.callback_data == _CALLBACK
    assert event.referenced_outbound_message_id == _OUTBOUND_ID


def test_message_api_clicked_cta_variant() -> None:
    payload = {
        "version": "1.0",
        "timestamp": "2024-06-10T08:38:08.837610",
        "type": "message_api_clicked",
        "data": {
            "customer": _customer(),
            "message": {
                "id": "abc-cta-1",
                "message_status": "Read",
                "message_content_type": "Template",
                "meta_data": {"source_data": {"callback_data": "ignored-here"}},
            },
        },
        "event": {
            "callbackData": _CALLBACK,
            "click_type": "CTA",
            "button_text": "Track Order",
            "button_link": "https://www.example.com/",
            "click_timestamp": "2024-06-10 08:47:26.948896",
        },
    }
    event = _do_normalize(payload)
    assert event.click_type == "CTA"
    assert event.button_text == "Track Order"
    # CTA top-level callbackData wins over meta_data.source_data.
    assert event.callback_data == _CALLBACK
    assert event.referenced_outbound_message_id == _OUTBOUND_ID


@pytest.mark.parametrize(
    ("event_type", "kind"),
    [
        ("message_api_sent", EventKind.OUTBOUND_SENT),
        ("message_api_delivered", EventKind.OUTBOUND_DELIVERED),
        ("message_api_read", EventKind.OUTBOUND_READ),
    ],
)
def test_outbound_status_events(event_type: str, kind: EventKind) -> None:
    payload = {
        "version": "1.0",
        "timestamp": "2024-06-10T08:38:08.837610",
        "type": event_type,
        "data": {
            "customer": _customer(),
            "message": {
                "id": "abc-status-1",
                "message_status": kind.value.split("_")[-1].capitalize(),
                "message_content_type": "Template",
                "meta_data": {"source_data": {"callback_data": _CALLBACK}},
            },
        },
    }
    event = _do_normalize(payload)
    assert event.event_kind is kind
    assert event.callback_data == _CALLBACK
    assert event.referenced_outbound_message_id == _OUTBOUND_ID
    assert event.text is None
    assert event.button_text is None


def test_outbound_failed_carries_failure_reason() -> None:
    payload = {
        "version": "1.0",
        "timestamp": "2024-06-10T08:38:08.837610",
        "type": "message_api_failed",
        "data": {
            "customer": _customer(),
            "message": {
                "id": "abc-fail-1",
                "message_status": "Failed",
                "channel_failure_reason": "Recipient is not a valid WhatsApp user",
                "message_content_type": "Template",
                "meta_data": {},
            },
        },
    }
    event = _do_normalize(payload)
    assert event.event_kind is EventKind.OUTBOUND_FAILED
    assert event.failure_reason == "Recipient is not a valid WhatsApp user"


def test_phone_falls_back_to_country_code_plus_phone() -> None:
    payload = {
        "version": "1.0",
        "timestamp": "2024-06-10T08:38:08.837610",
        "type": "message_received",
        "data": {
            "customer": {
                "id": "cust-2",
                "channel_phone_number": None,
                "phone_number": "7003705584",
                "country_code": "+91",
            },
            "message": {
                "id": "abc-text-2",
                "message_status": "Sent",
                "message_content_type": "Text",
                "message": "hi",
                "meta_data": {},
            },
        },
    }
    event = _do_normalize(payload)
    assert event.full_phone_number == "917003705584"


def test_missing_message_id_raises_normalization_error() -> None:
    payload = {
        "version": "1.0",
        "type": "message_received",
        "data": {
            "customer": _customer(),
            "message": {
                "id": None,
                "message_content_type": "Text",
                "message": "hi",
                "meta_data": {},
            },
        },
    }
    with pytest.raises(NormalizationError, match=r"data\.message\.id"):
        _do_normalize(payload)


def test_missing_phone_raises_normalization_error() -> None:
    payload = {
        "version": "1.0",
        "type": "message_received",
        "data": {
            "customer": {"id": "x"},
            "message": {
                "id": "abc",
                "message_content_type": "Text",
                "message": "hi",
                "meta_data": {},
            },
        },
    }
    with pytest.raises(NormalizationError, match="phone"):
        _do_normalize(payload)


def test_unsupported_event_type_raises() -> None:
    payload = {
        "version": "1.0",
        "type": "something_brand_new",
        "data": {
            "customer": _customer(),
            "message": {
                "id": "abc",
                "message_content_type": "Text",
                "message": "hi",
                "meta_data": {},
            },
        },
    }
    with pytest.raises(UnsupportedEventTypeError):
        _do_normalize(payload)


def test_callback_data_without_pipe_yields_no_outbound_ref() -> None:
    payload = {
        "version": "1.0",
        "type": "message_api_sent",
        "data": {
            "customer": _customer(),
            "message": {
                "id": "abc",
                "message_status": "Sent",
                "message_content_type": "Template",
                "meta_data": {"source_data": {"callback_data": "free-form text"}},
            },
        },
    }
    event = _do_normalize(payload)
    assert event.callback_data == "free-form text"
    assert event.referenced_outbound_message_id is None


def test_callback_data_with_non_uuid_head_yields_no_outbound_ref() -> None:
    payload = {
        "version": "1.0",
        "type": "message_api_sent",
        "data": {
            "customer": _customer(),
            "message": {
                "id": "abc",
                "message_status": "Sent",
                "message_content_type": "Template",
                "meta_data": {"source_data": {"callback_data": "not-a-uuid|corr"}},
            },
        },
    }
    event = _do_normalize(payload)
    assert event.referenced_outbound_message_id is None
