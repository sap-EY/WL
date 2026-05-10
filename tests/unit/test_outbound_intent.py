"""Tests for `wabot.domain.outbound.OutboundIntent`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from wabot.domain.outbound import InteractiveButton, OutboundIntent


def _phone() -> str:
    return "919999900001"


class TestInteractiveButton:
    def test_round_trips_valid_input(self) -> None:
        btn = InteractiveButton(id="reg_yes", title="Yes")
        assert btn.id == "reg_yes"
        assert btn.title == "Yes"

    def test_is_frozen(self) -> None:
        btn = InteractiveButton(id="reg_yes", title="Yes")
        with pytest.raises(ValidationError):
            btn.id = "x"  # type: ignore[misc]

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            InteractiveButton(id="x", title="t", extra="nope")  # type: ignore[call-arg]

    def test_rejects_empty_id(self) -> None:
        with pytest.raises(ValidationError):
            InteractiveButton(id="", title="t")

    def test_rejects_overlong_title(self) -> None:
        with pytest.raises(ValidationError):
            InteractiveButton(id="x", title="a" * 21)


class TestOutboundIntent:
    def test_text_intent(self) -> None:
        intent = OutboundIntent(
            kind="TEXT",
            full_phone_number=_phone(),
            symbol="msg.test",
            text="hello",
        )
        assert intent.kind == "TEXT"
        assert intent.text == "hello"
        assert intent.buttons is None

    def test_buttons_intent(self) -> None:
        intent = OutboundIntent(
            kind="BUTTONS",
            full_phone_number=_phone(),
            symbol="msg.test",
            text="pick",
            buttons=(InteractiveButton(id="a", title="A"),),
        )
        assert intent.buttons is not None
        assert intent.buttons[0].id == "a"

    def test_template_intent(self) -> None:
        intent = OutboundIntent(
            kind="TEMPLATE",
            full_phone_number=_phone(),
            symbol="msg.template",
            template_name="welcome_v1",
            body_values=("Dr Smith",),
        )
        assert intent.template_name == "welcome_v1"
        assert intent.body_values == ("Dr Smith",)

    def test_phone_too_short(self) -> None:
        with pytest.raises(ValidationError):
            OutboundIntent(
                kind="TEXT",
                full_phone_number="123",
                symbol="msg.test",
                text="hi",
            )

    def test_extra_forbid(self) -> None:
        with pytest.raises(ValidationError):
            OutboundIntent(  # type: ignore[call-arg]
                kind="TEXT",
                full_phone_number=_phone(),
                symbol="msg.test",
                text="hi",
                bogus=1,
            )

    def test_frozen(self) -> None:
        intent = OutboundIntent(
            kind="TEXT",
            full_phone_number=_phone(),
            symbol="msg.test",
            text="hi",
        )
        with pytest.raises(ValidationError):
            intent.text = "other"  # type: ignore[misc]
