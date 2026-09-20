"""Approved WhatsApp template content and deterministic local previews."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal
from urllib.parse import urlsplit

WhatsAppMessageType = Literal["welcome", "passport_link", "reminder", "group_invite"]

STATIC_TEMPLATE_HEADER = "Dear Delegates"
GREETING = "Greetings from Global Connect Travels."

PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT = (
    "Please fill in all required details, upload clear copies of the requested documents, "
    "and review everything carefully before submitting."
)

REMINDER_DEFAULT_MESSAGE_CONTENT = (
    "Kindly upload your documents using the provided link at the earliest. "
    "These details are required to process your application. If you have already "
    "submitted them, please ignore this reminder."
)

GROUP_INVITE_DEFAULT_MESSAGE_CONTENT = (
    "Please join our WhatsApp group using the link below to receive important trip updates "
    "and coordination details."
)


def validate_group_invite_link(value: str) -> str:
    """Accept official WhatsApp group invitations without changing their query parameters."""
    link = value.strip()
    try:
        parsed = urlsplit(link)
    except ValueError as exc:
        raise ValueError("Enter a valid WhatsApp group invite link starting with https://chat.whatsapp.com/.") from exc
    if (
        len(link) > 2048
        or any(character.isspace() or ord(character) < 32 for character in link)
        or parsed.scheme != "https"
        or parsed.netloc.lower() != "chat.whatsapp.com"
        or re.fullmatch(r"/[A-Za-z0-9]+/?", parsed.path) is None
        or parsed.fragment
    ):
        raise ValueError("Enter a valid WhatsApp group invite link starting with https://chat.whatsapp.com/.")
    return link

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
    "reminder": 1,
    "group_invite": 2,
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
    if message_type == "reminder":
        return REMINDER_DEFAULT_MESSAGE_CONTENT
    if message_type == "group_invite":
        return GROUP_INVITE_DEFAULT_MESSAGE_CONTENT
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
    group_invite_link: str | None = None,
) -> str:
    """Render the same message a recipient sees after Meta substitutes variables."""

    if message_type == "group_invite":
        return (
            "Dear Delegates\n\n"
            "Greetings from Global Connect Travels\n\n"
            f"{message_content}\n\n"
            f"{group_invite_link or '[WhatsApp group invite link]'}\n\n"
            "Regards\n"
            "Team Global Connect Travels"
        )
    if message_type == "welcome":
        return (
            f"{STATIC_TEMPLATE_HEADER}\n\n"
            f"{GREETING}\n\n"
            f"{message_content}\n\n"
            f"{AUTOMATED_NOTICE}\n\n"
            "Regards,\n"
            "Team Global Connect Travels"
        )
    if message_type == "reminder":
        return (
            "URGENT REMINDER !!\n\n"
            "Dear Delegates\n\n"
            "Greetings from Global Connect Travels\n\n"
            f"{message_content}\n\n"
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
    group_invite_link: str | None = None,
) -> list[str]:
    """Return positional BODY variables in the exact Meta template order."""

    if message_type == "group_invite":
        return [message_content, group_invite_link or ""]
    if message_type == "welcome":
        return [message_content]
    if message_type == "reminder":
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

    if message_type in {"reminder", "group_invite"}:
        return []
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

    if message_type == "group_invite":
        if header_parameters or len(body_parameters) != 2:
            raise ValueError("group_invite requires no header and exactly two body parameters")
        if not isinstance(body_parameters[1], str):
            raise ValueError("WhatsApp template parameters must contain non-empty text")
        validate_group_invite_link(body_parameters[1])
    elif message_type == "reminder":
        if header_parameters or len(body_parameters) != 1:
            raise ValueError(
                "reminder requires no media header and exactly one body parameter"
            )
    elif message_type == "welcome":
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
        message_type not in {"welcome", "reminder"}
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
