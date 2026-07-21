"""Deterministic content for approved WhatsApp document templates."""

from __future__ import annotations

from collections.abc import Sequence

DOCUMENT_TYPE_LABELS = {
    "visa": "Visa",
    "flight_ticket": "Flight Ticket",
    "other": "Travel Document",
}


def document_type_label(document_type: str) -> str:
    return DOCUMENT_TYPE_LABELS.get(document_type, "Travel Document")


def document_template_parameters(
    *,
    passenger_name: str,
    document_type: str,
    group_name: str,
) -> list[str]:
    """Return BODY variables for the approved document-header template."""

    parameters = [
        passenger_name.strip(),
        document_type_label(document_type),
        group_name.strip(),
    ]
    validate_document_template_parameters(parameters)
    return parameters


def validate_document_template_parameters(parameters: Sequence[str]) -> None:
    if len(parameters) != 3:
        raise ValueError("document delivery requires exactly three body parameters")
    if any(not isinstance(value, str) or not value.strip() for value in parameters):
        raise ValueError("document delivery template parameters must be non-empty")


def render_document_message(
    *,
    passenger_name: str,
    document_type: str,
    group_name: str,
) -> str:
    label = document_type_label(document_type)
    return (
        f"Dear {passenger_name.strip()},\n\n"
        f"Your {label} for {group_name.strip()} is attached. "
        "Please download and review it carefully.\n\n"
        "Regards,\n"
        "Team Global Connect Travels"
    )
