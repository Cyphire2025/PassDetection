"""Deterministic content for approved WhatsApp document templates."""

from __future__ import annotations

from collections.abc import Sequence

DOCUMENT_DEFAULT_MESSAGE_CONTENT = {
    "visa": "This is your attached VISA",
    "flight_ticket": "This is your attached DEPARTURE FLIGHT TICKET",
    "flight_ticket_arrival": "This is your attached ARRIVAL FLIGHT TICKET",
    "other": "This is your attached TRAVEL DOCUMENT",
}
DOCUMENT_DEFAULT_REVIEW_CONTENT = "Kindly cross check all your details"


def document_type_label(document_type: str) -> str:
    return {
        "visa": "Visa",
        "flight_ticket": "Departure Flight Ticket",
        "flight_ticket_arrival": "Arrival Flight Ticket",
        "other": "Travel Document",
    }.get(document_type, "Travel Document")


def default_document_message_content(document_type: str) -> tuple[str, str]:
    return (
        DOCUMENT_DEFAULT_MESSAGE_CONTENT.get(
            document_type,
            DOCUMENT_DEFAULT_MESSAGE_CONTENT["other"],
        ),
        DOCUMENT_DEFAULT_REVIEW_CONTENT,
    )


def document_template_parameters(
    *,
    message_content_1: str,
    message_content_2: str,
) -> list[str]:
    """Return BODY variables for the approved documents_v1 template."""

    parameters = [
        message_content_1.strip(),
        message_content_2.strip(),
    ]
    validate_document_template_parameters(parameters)
    return parameters


def legacy_document_template_parameters(
    *,
    passenger_name: str,
    document_type: str,
    group_name: str,
) -> list[str]:
    """Keep already-queued deliveries compatible during a rolling deployment."""

    parameters = [
        passenger_name.strip(),
        document_type_label(document_type),
        group_name.strip(),
    ]
    if any(not value for value in parameters):
        raise ValueError("legacy document delivery parameters must be non-empty")
    return parameters


def validate_document_template_parameters(parameters: Sequence[str]) -> None:
    if len(parameters) not in {2, 3}:
        raise ValueError(
            "document delivery requires two current or three legacy body parameters"
        )
    if any(not isinstance(value, str) or not value.strip() for value in parameters):
        raise ValueError("document delivery template parameters must be non-empty")


def render_document_message(
    *,
    message_content_1: str,
    message_content_2: str,
) -> str:
    return (
        "Dear Delegates\n\n"
        "Greetings from Global Connect Travels\n\n"
        f"{message_content_1.strip()}\n\n"
        f"{message_content_2.strip()}\n\n"
        "Regards,\n"
        "Team Global Connect Travels"
    )
