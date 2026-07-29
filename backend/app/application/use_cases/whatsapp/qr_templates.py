"""Deterministic content for the approved passenger QR WhatsApp template."""

from __future__ import annotations

from collections.abc import Sequence

QR_DEFAULT_MESSAGE_CONTENT = (
    "This is Specialized QR code generated for you, please save this, it will "
    "be used for keeping a track during the trip in all activities"
)


def qr_template_parameters(*, message_content: str) -> list[str]:
    parameters = [message_content.strip()]
    validate_qr_template_parameters(parameters)
    return parameters


def validate_qr_template_parameters(parameters: Sequence[str]) -> None:
    if len(parameters) != 1:
        raise ValueError("QR delivery requires exactly one body parameter")
    if any(not isinstance(value, str) or not value.strip() for value in parameters):
        raise ValueError("QR delivery template parameters must be non-empty")


def render_qr_message(*, message_content: str) -> str:
    return (
        "Dear Delegates\n\n"
        "Greetings from Global Connect Travels\n\n"
        f"{message_content.strip()}\n\n"
        "Regards,\n"
        "Team Global Connect Travels"
    )
