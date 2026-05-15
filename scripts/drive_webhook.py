"""Local Interakt-webhook driver for manual end-to-end testing.

Builds canonical Interakt payloads (matching `interakt_webhook.md` sample
shapes) and POSTs them to `http://localhost:8000/webhooks/<secret>/interakt`
exactly like Interakt would, so you can drive both journeys without a
public tunnel.

Pre-reqs (each in a separate terminal):

  1. ``docker compose up -d redis``      # Redis must be reachable
  2. ``uvicorn wabot.main:app --port 8000 --reload``
  3. ``WABOT_USE_FAKE_GENAI=true python -m wabot.workers.inbound_worker``
     (omit the env var to exercise the Phase 8 fallback path instead)

Examples:

  # 1. Fresh user, type 'hi' — registration prompt comes back to WhatsApp.
  python scripts/drive_webhook.py text 9867401411 "hi"

  # 2. Submit the 7-field registration in one message.
  python scripts/drive_webhook.py text 9867401411 \
      "Test Doctor#Cardiology#221B Baker St#test@example.com#Mumbai#Maharashtra#400001"

  # 3. Tap the consent 'Let's continue' button.
  python scripts/drive_webhook.py button 9867401411 "Let's continue"

  # 4. List of canned scenarios at a glance:
  python scripts/drive_webhook.py --list
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from wabot.infra.config import get_settings

# ---------------------------------------------------------------------------
# Payload builders (mirror `interakt_webhook.md` sample shapes verbatim)
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _customer(phone: str) -> dict[str, Any]:
    return {
        "id": "52918eb3-bd00-4331-a51d-c4dcffee48d6",
        "channel_phone_number": phone,
        "traits": {
            "name": "Local Test",
            "whatsapp_opted_in": True,
        },
    }


def _text_payload(phone: str, text: str) -> dict[str, Any]:
    return {
        "version": "1.0",
        "timestamp": _now_iso(),
        "type": "message_received",
        "data": {
            "customer": _customer(phone),
            "message": {
                "id": str(uuid.uuid4()),
                "chat_message_type": "CustomerMessage",
                "channel_failure_reason": None,
                "message_status": "Sent",
                "received_at_utc": _now_iso(),
                "delivered_at_utc": None,
                "seen_at_utc": None,
                "campaign_id": None,
                "is_template_message": False,
                "raw_template": None,
                "channel_error_code": None,
                "message_content_type": "Text",
                "media_url": None,
                "message": text,
                "meta_data": {},
            },
        },
    }


def _button_reply_payload(phone: str, button_title: str) -> dict[str, Any]:
    return {
        "version": "1.0",
        "timestamp": _now_iso(),
        "type": "message_received",
        "data": {
            "customer": _customer(phone),
            "message": {
                "id": str(uuid.uuid4()),
                "chat_message_type": "CustomerMessage",
                "channel_failure_reason": None,
                "message_status": "Sent",
                "received_at_utc": _now_iso(),
                "delivered_at_utc": None,
                "seen_at_utc": None,
                "campaign_id": None,
                "is_template_message": False,
                "raw_template": None,
                "channel_error_code": None,
                "message_content_type": "Interactive",
                "media_url": None,
                "message": button_title,
                "meta_data": {
                    "button_payload": {
                        "payload": {
                            "text": button_title,
                        }
                    }
                },
            },
        },
    }


def _flow_response_payload(phone: str, response_json: dict[str, Any]) -> dict[str, Any]:
    """Build a ``message_api_flow_response`` payload matching wa_form.txt."""
    return {
        "version": "1.0",
        "timestamp": _now_iso(),
        "type": "message_api_flow_response",
        "data": {
            "customer": _customer(phone),
            "message": {
                "id": str(uuid.uuid4()),
                "chat_message_type": "CustomerMessage",
                "channel_failure_reason": None,
                "message_status": "Sent",
                "received_at_utc": _now_iso(),
                "delivered_at_utc": None,
                "seen_at_utc": None,
                "campaign_id": None,
                "is_template_message": False,
                "raw_template": None,
                "channel_error_code": None,
                "message_content_type": "InteractiveFlowReply",
                "media_url": None,
                "message": {
                    "type": "nfm_reply",
                    "nfm_reply": {
                        "response_json": response_json,
                        "body": "Sent",
                        "name": "flow",
                    },
                },
                "meta_data": {},
            },
            "source_template_message": {
                "template_name": "user_registration_v1",
                "campaign_id": None,
                "callback_data": None,
                "status": "Sent",
                "is_campaign": False,
                "message_type": "PublicApiMessage",
            },
            "flow_id": 985469590600160,
        },
    }


# ---------------------------------------------------------------------------
# Canned scenarios — quick lookup table
# ---------------------------------------------------------------------------


_SCENARIOS = (
    (
        "text   <phone> 'hi'                                ",
        "Case A: fresh inbound → user_registration_v1 template",
    ),
    (
        'flow   <phone> \'{"screen_0_first_name_0": "Jane", ...}\'',
        "Form submission → registration completed",
    ),
    (
        "button <phone> \"Let's continue\" / 'No, thanks'   ",
        "Consent template reply",
    ),
    (
        "button <phone> 'Call hotline'                      ",
        "Ice-breaker → hotline template (or just send free text to talk to GenAI)",
    ),
    (
        "text   <phone> 'What is the dose of paracetamol?'  ",
        "Scientific GenAI branch (needs WABOT_USE_FAKE_GENAI=true)",
    ),
    ("button <phone> 'Satisfied' / 'Call hotline'        ", "Answer-button reply"),
)


def _print_scenarios() -> int:
    print("Canned scenarios (run after `seed_state.py` puts the doctor in the right state):\n")
    for cmd, desc in _SCENARIOS:
        print(f"  {cmd}  # {desc}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_url(host: str, port: int) -> str:
    settings = get_settings()
    secret = settings.interakt_webhook_path_secret.get_secret_value()
    return f"http://{host}:{port}/webhooks/{secret}/interakt"


def _post(payload: dict[str, Any], *, host: str, port: int) -> int:
    url = _build_url(host, port)
    print(f"POST {url}")
    print(json.dumps(payload, indent=2))
    response = httpx.post(url, json=payload, timeout=5.0)
    print(f"\n-> {response.status_code} {response.reason_phrase}")
    if response.content:
        try:
            print(json.dumps(response.json(), indent=2))
        except ValueError:
            print(response.text)
    return 0 if response.status_code < 400 else 1


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Drive the local Interakt webhook with canonical payloads."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--list", action="store_true", help="Print canned scenarios and exit")

    sub = parser.add_subparsers(dest="kind")

    p_text = sub.add_parser("text", help="Send a free-text message")
    p_text.add_argument("phone")
    p_text.add_argument("text")

    p_btn = sub.add_parser("button", help="Send a quick-reply button tap")
    p_btn.add_argument("phone")
    p_btn.add_argument("button_title")

    p_flow = sub.add_parser("flow", help="Send a WhatsApp Flow form submission")
    p_flow.add_argument("phone")
    p_flow.add_argument(
        "response_json",
        help=(
            "JSON dict of form field -> value (Interakt prefixes the keys with "
            "screen_<n>_). Example: "
            '\'{"screen_0_first_name_0": "Jane", "screen_0_last_name_1": "Doe", '
            '"screen_0_mci_id_2": "12345", "screen_0_speciality_3": ["Cardiology"]}\''
        ),
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.list or not args.kind:
        return _print_scenarios()
    if args.kind == "text":
        payload = _text_payload(args.phone, args.text)
    elif args.kind == "button":
        payload = _button_reply_payload(args.phone, args.button_title)
    elif args.kind == "flow":
        try:
            parsed = json.loads(args.response_json)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON for response_json: {exc}", file=sys.stderr)
            return 2
        if not isinstance(parsed, dict):
            print("response_json must decode to a JSON object", file=sys.stderr)
            return 2
        payload = _flow_response_payload(args.phone, parsed)
    else:  # pragma: no cover
        return 2
    return _post(payload, host=args.host, port=args.port)


if __name__ == "__main__":
    raise SystemExit(main())
