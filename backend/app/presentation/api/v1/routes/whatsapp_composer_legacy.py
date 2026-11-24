"""Verify legacy saved text against its original deterministic template."""

from __future__ import annotations

from urllib.parse import urlparse

from app.application.use_cases.whatsapp.message_templates import (
    AUTOMATED_NOTICE,
    GREETING,
    PASSPORT_INFORMATION_NOTICE,
    STATIC_TEMPLATE_HEADER,
    WhatsAppMessageType,
    passport_link_intro,
    render_message,
    validate_template_parameters,
)


def _split_rendered_support_block(rendered_body: str) -> tuple[str, str]:
    assistance_marker = "\n\nFor assistance, please contact:\n"
    footer = "\n\nRegards,\nTeam Global Connect Travels"
    before_support, marker, support_and_footer = rendered_body.rpartition(assistance_marker)
    if not marker:
        raise ValueError("The saved WhatsApp message has an unknown assistance layout")
    support_contacts, footer_marker, trailing = support_and_footer.rpartition(footer)
    if not footer_marker or trailing or not support_contacts.strip():
        raise ValueError("The saved WhatsApp message has an unknown footer layout")
    return before_support, support_contacts


def _decode_legacy_template_snapshot(
    *,
    message_type: WhatsAppMessageType,
    rendered_message: str | None,
) -> tuple[list[str], list[str]]:
    """Decode only messages that exactly match our deterministic approved layout."""

    if not rendered_message:
        raise ValueError("The saved WhatsApp message has no reusable content")
    prefix = f"{STATIC_TEMPLATE_HEADER}\n\n{GREETING}\n\n"
    if not rendered_message.startswith(prefix):
        raise ValueError("The saved WhatsApp message has an unknown header layout")
    before_support, support_contacts = _split_rendered_support_block(
        rendered_message[len(prefix) :]
    )

    if message_type == "welcome":
        notice_suffix = f"\n\n{AUTOMATED_NOTICE}"
        if not before_support.endswith(notice_suffix):
            raise ValueError("The saved welcome message has an unknown notice layout")
        message_content = before_support[: -len(notice_suffix)]
        header_parameters: list[str] = []
        parameters = [message_content, support_contacts]
        reconstructed = (
            f"{STATIC_TEMPLATE_HEADER}\n\n"
            f"{GREETING}\n\n"
            f"{message_content}\n\n"
            f"{AUTOMATED_NOTICE}\n\n"
            "For assistance, please contact:\n"
            f"{support_contacts}\n\n"
            "Regards,\n"
            "Team Global Connect Travels"
        )
    else:
        notice_suffix = f"\n\n{PASSPORT_INFORMATION_NOTICE}"
        if not before_support.endswith(notice_suffix):
            raise ValueError("The saved passport message has an unknown notice layout")
        variable_area = before_support[: -len(notice_suffix)]
        try:
            intro, passport_link, message_content = variable_area.split("\n\n", 2)
        except ValueError as exc:
            raise ValueError(
                "The saved passport message does not contain the approved variables"
            ) from exc
        intro_prefix = (
            "Please use the secure link below to submit your travel documents required for "
            "your trip to "
        )
        if (
            not intro.startswith(intro_prefix)
            or not intro.endswith(".")
            or not intro[len(intro_prefix) : -1].strip()
        ):
            raise ValueError("The saved passport message has an unknown trip introduction")
        original_group_name = intro[len(intro_prefix) : -1]
        parsed_link = urlparse(passport_link)
        if parsed_link.scheme not in {"http", "https"} or not parsed_link.netloc:
            raise ValueError("The saved passport message has an invalid upload link")
        if intro != passport_link_intro(original_group_name):
            raise ValueError("The saved passport message trip introduction is inconsistent")
        header_parameters = []
        parameters = [
            intro,
            passport_link,
            message_content,
            support_contacts,
        ]
        reconstructed = render_message(
            message_type=message_type,
            group_name=original_group_name,
            support_contacts=support_contacts,
            message_content=message_content,
            passport_link=passport_link,
        )

    validate_template_parameters(
        message_type=message_type,
        header_parameters=header_parameters,
        body_parameters=parameters,
    )
    if reconstructed != rendered_message:
        raise ValueError("The saved WhatsApp message could not be verified exactly")
    return header_parameters, parameters


# Keep existing public imports and pickle identities.
_split_rendered_support_block.__module__ = (
    "app.presentation.api.v1.routes.whatsapp_composer_support"
)
_decode_legacy_template_snapshot.__module__ = (
    "app.presentation.api.v1.routes.whatsapp_composer_support"
)
