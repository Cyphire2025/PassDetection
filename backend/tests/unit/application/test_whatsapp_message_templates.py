"""Regression tests for approved WhatsApp message bodies and variable order."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.application.use_cases.whatsapp.message_templates import (
    PASSPORT_INFORMATION_NOTICE,
    PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT,
    default_message_content,
    format_support_contacts,
    passport_link_intro,
    render_message,
    template_header_parameters,
    template_parameters,
    validate_template_parameters,
)
from app.application.use_cases.whatsapp.plan_group_broadcast_use_case import (
    template_for_intent,
)


class WhatsAppMessageTemplateTests(unittest.TestCase):
    def test_welcome_message_matches_approved_copy_without_recipient_or_company(self) -> None:
        support = format_support_contacts(
            [("Yogesh Kumar Vashistha", "+91 98187 52221")]
        )
        message_content = default_message_content(
            "welcome",
            group_name="Thailand Leadership Trip",
        )
        rendered = render_message(
            message_type="welcome",
            group_name="Thailand Leadership Trip",
            support_contacts=support,
            message_content=message_content,
        )

        self.assertEqual(
            rendered,
            "Dear Delegates\n\n"
            "Greetings from Global Connect Travels.\n\n"
            'This message is regarding your upcoming trip to "Thailand Leadership Trip".\n\n'
            "This is an automated notification sent individually to you. Replies to this "
            "WhatsApp message are not monitored and will not be treated as support requests."
            "\n\n"
            "Regards,\n"
            "Team Global Connect Travels",
        )
        self.assertNotIn("Aarav Sharma", rendered)
        self.assertNotIn("Bluechip", rendered)

    def test_welcome_template_parameter_order_matches_meta_template(self) -> None:
        header_parameters = template_header_parameters(
            message_type="welcome",
            welcome_image_id="media-123",
        )
        parameters = template_parameters(
            message_type="welcome",
            group_name="Vietnam Leadership Trip 2026",
            support_contacts="Raman Jha: +91 98187 52221",
            message_content='This message is regarding your upcoming trip to "Thailand".',
        )

        self.assertEqual(header_parameters, ["media-123"])
        self.assertEqual(
            parameters,
            [
                'This message is regarding your upcoming trip to "Thailand".',
            ],
        )
        validate_template_parameters(
            message_type="welcome",
            header_parameters=header_parameters,
            body_parameters=parameters,
        )

    def test_passport_template_parameter_order_matches_meta_template(self) -> None:
        self.assertEqual(
            template_header_parameters(
                message_type="passport_link",
            ),
            [],
        )
        parameters = template_parameters(
            message_type="passport_link",
            group_name="Thailand",
            passport_link="https://travel.example/upload/abc",
            support_contacts="Raman Jha: +91 98187 52221",
            message_content=PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT,
        )

        self.assertEqual(
            parameters,
            [
                "Please use the secure link below to submit your travel documents required "
                "for your trip to Thailand.",
                "https://travel.example/upload/abc",
                "Please fill in all required details, upload clear copies of the requested "
                "documents, and review everything carefully before submitting.",
                "Raman Jha: +91 98187 52221",
            ],
        )
        validate_template_parameters(
            message_type="passport_link",
            header_parameters=[],
            body_parameters=parameters,
        )

    def test_passport_preview_matches_approved_fixed_body_text(self) -> None:
        rendered = render_message(
            message_type="passport_link",
            group_name="Thailand",
            passport_link="https://travel.example/upload/abc",
            support_contacts="Raman Jha: +91 98187 52221",
            message_content=PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT,
        )

        self.assertEqual(
            rendered,
            "Dear Delegates\n\n"
            "Greetings from Global Connect Travels.\n\n"
            f"{passport_link_intro('Thailand')}\n\n"
            "https://travel.example/upload/abc\n\n"
            f"{PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT}\n\n"
            f"{PASSPORT_INFORMATION_NOTICE}\n\n"
            "For assistance, please contact:\n"
            "Raman Jha: +91 98187 52221\n\n"
            "Regards,\n"
            "Team Global Connect Travels",
        )

    def test_defaults_and_support_format_are_stable(self) -> None:
        self.assertEqual(
            default_message_content("welcome", group_name="Thailand"),
            'This message is regarding your upcoming trip to "Thailand".',
        )
        self.assertEqual(
            default_message_content("passport_link", group_name="Thailand"),
            PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT,
        )
        self.assertEqual(
            format_support_contacts(
                [
                    ("Raman Jha", "+91 98187 52221"),
                    ("Helpdesk", "9876543211"),
                ]
            ),
            "Raman Jha: +91 98187 52221\nHelpdesk: 9876543211",
        )

    def test_parameter_validation_requires_welcome_image_and_exact_body_counts(self) -> None:
        with self.assertRaisesRegex(ValueError, "one image header"):
            validate_template_parameters(
                message_type="welcome",
                header_parameters=[],
                body_parameters=["Trip message"],
            )
        with self.assertRaisesRegex(ValueError, "exactly 4"):
            validate_template_parameters(
                message_type="passport_link",
                header_parameters=[],
                body_parameters=["intro", "https://example.test", "instructions"],
            )

    def test_planner_uses_central_runtime_names_and_language(self) -> None:
        with patch(
            "app.application.use_cases.whatsapp.plan_group_broadcast_use_case.get_settings",
            return_value=SimpleNamespace(
                whatsapp_welcome_template_name="approved_welcome",
                whatsapp_passport_link_template_name="approved_passport",
                whatsapp_template_language="en_US",
            ),
        ):
            welcome = template_for_intent("welcome")
            passport = template_for_intent("passport_upload_link")

        self.assertEqual(welcome.template_name, "approved_welcome")
        self.assertEqual(passport.template_name, "approved_passport")
        self.assertEqual(welcome.language_code, "en_US")
        self.assertEqual(passport.language_code, "en_US")


if __name__ == "__main__":
    unittest.main()
