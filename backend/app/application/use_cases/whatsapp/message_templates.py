"""Approved WhatsApp template content and deterministic local previews."""

from __future__ import annotations

from typing import Literal, Sequence


WhatsAppMessageType = Literal["welcome", "passport_link"]

WELCOME_TEMPLATE_NAME = "global_connect_welcome_v1"
PASSPORT_LINK_TEMPLATE_NAME = "global_connect_passport_link_v1"

WELCOME_DEFAULT_MESSAGE_CONTENT = (
    "All further information, important updates, and arrangements regarding your trip "
    "will be shared with you here."
)

PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT = (
    "Please complete all required fields, upload a clear scan of the passport information "
    "page and a recent photograph with a plain white or light background, and carefully "
    "verify every entry before submitting."
)

AUTOMATED_NOTICE = (
    "This is an automated notification sent individually to you. Replies to this WhatsApp "
    "message are not monitored and will not be treated as support requests."
)


def default_message_content(message_type: WhatsAppMessageType) -> str:
    if message_type == "welcome":
        return WELCOME_DEFAULT_MESSAGE_CONTENT
    return PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT


def format_support_contacts(contacts: Sequence[tuple[str, str]]) -> str:
    """Format contacts exactly as supplied to the approved template variable."""

    if not contacts:
        return "Please contact your company travel coordinator."
    return "\n".join(f"- {name}: {phone_number}" for name, phone_number in contacts)


def render_message(
    *,
    message_type: WhatsAppMessageType,
    recipient_name: str,
    group_name: str,
    organizing_company_name: str,
    support_contacts: str,
    message_content: str,
    passport_link: str | None = None,
) -> str:
    """Render the same message a recipient sees after Meta substitutes variables."""

    if message_type == "welcome":
        return (
            f"Dear {recipient_name},\n\n"
            "Greetings from Global Connect Travels.\n\n"
            f"This message concerns your upcoming trip under the group \"{group_name}\", "
            f"organised by {organizing_company_name}.\n\n"
            f"{message_content}\n\n"
            f"{AUTOMATED_NOTICE}\n\n"
            "For assistance, please contact:\n"
            f"{support_contacts}\n\n"
            "Regards,\n"
            "Team Global Connect Travels"
        )

    return (
        f"Dear {recipient_name},\n\n"
        "Please use the secure link below to submit the passport information and documents "
        f"required for your group \"{group_name}\", organised by {organizing_company_name}:\n\n"
        f"{passport_link or '[passport upload link]'}\n\n"
        f"{message_content}\n\n"
        "The information and documents submitted through this link will be used for visa "
        "processing and issuance. Incorrect or incomplete details may delay the application, "
        "so please complete the form as soon as possible.\n\n"
        "For assistance, please contact:\n"
        f"{support_contacts}\n\n"
        "Regards,\n"
        "Team Global Connect Travels"
    )


def template_parameters(
    *,
    message_type: WhatsAppMessageType,
    recipient_name: str,
    group_name: str,
    organizing_company_name: str,
    support_contacts: str,
    message_content: str,
    passport_link: str | None = None,
) -> list[str]:
    """Return positional BODY variables in the exact Meta template order."""

    if message_type == "welcome":
        return [
            group_name,
            organizing_company_name,
            message_content,
            support_contacts,
        ]
    return [
        group_name,
        organizing_company_name,
        passport_link or "",
        message_content,
        support_contacts,
    ]


def template_header_parameters(
    *,
    message_type: WhatsAppMessageType,
    recipient_name: str,
) -> list[str]:
    """Return positional HEADER variables in the exact Meta template order."""

    if message_type in {"welcome", "passport_link"}:
        return [recipient_name]
    return []
