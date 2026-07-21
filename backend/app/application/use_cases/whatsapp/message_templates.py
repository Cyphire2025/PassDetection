"""Approved WhatsApp template content and deterministic local previews."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

WhatsAppMessageType = Literal["welcome", "passport_link"]

STATIC_TEMPLATE_HEADER = "Dear Delegates"
GREETING = "Greetings from Global Connect Travels."

PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT = (
    "Please fill in all required details, upload clear copies of the requested documents, "
    "and review everything carefully before submitting."
)

AUTOMATED_NOTICE = (
    "This is an automated notification sent individually to you. Replies to this WhatsApp "
    "message are not monitored and will not be treated as support requests."
)

PASSPORT_INFORMATION_NOTICE = (
    "The information and documents submitted through this link will be used to make your "
    "travel arrangements. Please ensure all details are accurate and complete, as incorrect "
    "or missing information may delay the application process. Kindly complete the form at "
    "your earliest convenience."
)

EXPECTED_BODY_PARAMETER_COUNTS: dict[WhatsAppMessageType, int] = {
    "welcome": 1,
    "passport_link": 4,
}


def welcome_default_message_content(group_name: str) -> str:
    """Build approved BODY {{1}} using only the saved group name."""

    return f'This message is regarding your upcoming trip to "{group_name}".'


def passport_link_intro(group_name: str) -> str:
    """Build approved passport BODY {{1}} using only the saved group name."""

    return (
        "Please use the secure link below to submit your travel documents required for "
        f"your trip to {group_name}."
    )


def default_message_content(message_type: WhatsAppMessageType, *, group_name: str) -> str:
    if message_type == "welcome":
        return welcome_default_message_content(group_name)
    return PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT


def format_support_contacts(contacts: Sequence[tuple[str, str]]) -> str:
    """Format contacts exactly as supplied to the approved template variable."""

    if not contacts:
        return "Please contact your company travel coordinator."
    return "\n".join(f"{name}: {phone_number}" for name, phone_number in contacts)


def render_message(
    *,
    message_type: WhatsAppMessageType,
    group_name: str,
    support_contacts: str,
    message_content: str,
    passport_link: str | None = None,
    passport_intro: str | None = None,
) -> str:
    """Render the same message a recipient sees after Meta substitutes variables."""

    if message_type == "welcome":
        return (
            f"{STATIC_TEMPLATE_HEADER}\n\n"
            f"{GREETING}\n\n"
            f"{message_content}\n\n"
            f"{AUTOMATED_NOTICE}\n\n"
            "Regards,\n"
            "Team Global Connect Travels"
        )

    return (
        f"{STATIC_TEMPLATE_HEADER}\n\n"
        f"{GREETING}\n\n"
        f"{passport_intro if passport_intro is not None else passport_link_intro(group_name)}\n\n"
        f"{passport_link or '[passport upload link]'}\n\n"
        f"{message_content}\n\n"
        f"{PASSPORT_INFORMATION_NOTICE}\n\n"
        "For assistance, please contact:\n"
        f"{support_contacts}\n\n"
        "Regards,\n"
        "Team Global Connect Travels"
    )


def template_parameters(
    *,
    message_type: WhatsAppMessageType,
    group_name: str,
    support_contacts: str,
    message_content: str,
    passport_link: str | None = None,
    passport_intro: str | None = None,
) -> list[str]:
    """Return positional BODY variables in the exact Meta template order."""

    if message_type == "welcome":
        return [message_content]
    return [
        passport_intro if passport_intro is not None else passport_link_intro(group_name),
        passport_link or "",
        message_content,
        support_contacts,
    ]


def template_header_parameters(
    *,
    message_type: WhatsAppMessageType,
    welcome_image_id: str | None = None,
    header_image_id: str | None = None,
) -> list[str]:
    """Return positional HEADER variables in the exact Meta template order."""

    resolved_image_id = header_image_id or welcome_image_id
    if resolved_image_id:
        return [resolved_image_id]
    return []


def validate_template_parameters(
    *,
    message_type: WhatsAppMessageType,
    header_parameters: Sequence[str],
    body_parameters: Sequence[str],
) -> None:
    """Reject payloads that cannot match the approved Meta templates."""

    if message_type == "welcome":
        is_current_media_template = (
            len(header_parameters) == 1 and len(body_parameters) == 1
        )
        is_legacy_text_template = (
            len(header_parameters) == 0 and len(body_parameters) == 2
        )
        if not (is_current_media_template or is_legacy_text_template):
            raise ValueError(
                "welcome requires one image header and one body parameter"
            )
    else:
        is_current_media_template = len(header_parameters) == 1
        is_legacy_text_template = len(header_parameters) == 0
        if not (is_current_media_template or is_legacy_text_template):
            raise ValueError(
                "passport_link requires one image header for the current template"
            )

    expected_body_count = EXPECTED_BODY_PARAMETER_COUNTS[message_type]
    if (
        message_type != "welcome"
        and len(body_parameters) != expected_body_count
    ):
        raise ValueError(
            f"{message_type} requires exactly {expected_body_count} body parameters"
        )
    if any(
        not isinstance(value, str) or not value.strip()
        for value in [*header_parameters, *body_parameters]
    ):
        raise ValueError("WhatsApp template parameters must contain non-empty text")
