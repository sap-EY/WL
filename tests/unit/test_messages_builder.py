"""Tests for `wabot.domain.messages.builder`."""

from __future__ import annotations

import pytest

from wabot.domain.messages import (
    ButtonId,
    MessageBuildError,
    MessageSymbol,
    build_buttons,
    build_template,
    build_text,
)

_PHONE = "919999900001"


class TestBuildText:
    def test_uses_catalog_text(self) -> None:
        intent = build_text(
            symbol=MessageSymbol.MSG_REG_FULL_DETAILS_PROMPT,
            full_phone_number=_PHONE,
        )
        assert intent.kind == "TEXT"
        assert intent.text  # catalog populates copy
        assert intent.symbol == MessageSymbol.MSG_REG_FULL_DETAILS_PROMPT.value

    def test_text_override_wins(self) -> None:
        intent = build_text(
            symbol=MessageSymbol.MSG_REG_FULL_DETAILS_PROMPT,
            full_phone_number=_PHONE,
            text_override="custom",
        )
        assert intent.text == "custom"

    def test_kind_mismatch_raises(self) -> None:
        with pytest.raises(MessageBuildError):
            build_text(
                symbol=MessageSymbol.MSG_REGISTERED_ANSWER_WITH_BUTTONS,
                full_phone_number=_PHONE,
            )


class TestBuildButtons:
    def test_happy_path(self) -> None:
        intent = build_buttons(
            symbol=MessageSymbol.MSG_REGISTERED_ANSWER_WITH_BUTTONS,
            full_phone_number=_PHONE,
            buttons=[
                (ButtonId.REGISTERED_ANSWER_SATISFIED, "Yes"),
                (ButtonId.REGISTERED_ANSWER_CALL_HOTLINE, "Call hotline"),
            ],
            text_override="answer body",
        )
        assert intent.kind == "BUTTONS"
        assert intent.buttons is not None
        assert len(intent.buttons) == 2
        assert intent.buttons[0].id == ButtonId.REGISTERED_ANSWER_SATISFIED.value

    def test_empty_buttons_raises(self) -> None:
        with pytest.raises(MessageBuildError):
            build_buttons(
                symbol=MessageSymbol.MSG_REGISTERED_ANSWER_WITH_BUTTONS,
                full_phone_number=_PHONE,
                buttons=[],
                text_override="x",
            )

    def test_kind_mismatch_raises(self) -> None:
        with pytest.raises(MessageBuildError):
            build_buttons(
                symbol=MessageSymbol.MSG_REG_FULL_DETAILS_PROMPT,
                full_phone_number=_PHONE,
                buttons=[("a", "A")],
            )


class TestBuildTemplate:
    def test_happy_path(self) -> None:
        intent = build_template(
            symbol=MessageSymbol.TEMPLATE_DOCTOR_WELCOME_CONSENT,
            full_phone_number=_PHONE,
            template_name="doctor_welcome_consent_v1",
            body_values=["Dr Smith"],
        )
        assert intent.kind == "TEMPLATE"
        assert intent.template_name == "doctor_welcome_consent_v1"
        assert intent.body_values == ("Dr Smith",)

    def test_kind_mismatch_raises(self) -> None:
        with pytest.raises(MessageBuildError):
            build_template(
                symbol=MessageSymbol.MSG_REG_FULL_DETAILS_PROMPT,
                full_phone_number=_PHONE,
                template_name="x",
            )
