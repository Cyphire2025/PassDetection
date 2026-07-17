"""Regression tests for approved WhatsApp message bodies and variable order."""

from __future__ import annotations

import unittest

from app.application.use_cases.whatsapp.message_templates import (
    PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT,
    WELCOME_DEFAULT_MESSAGE_CONTENT,
    default_message_content,
    format_support_contacts,
    render_message,
    template_header_parameters,
    template_parameters,
)


class WhatsAppMessageTemplateTests(unittest.TestCase):
    def test_welcome_message_is_personalised_and_marks_replies_unmonitored(self) -> None:
        support = format_support_contacts(
            [("Yogesh Kumar Vashistha", "+91 98187 52221")]
        )
        rendered = render_message(
            message_type="welcome",
            recipient_name="Aarav Sharma",
            group_name="Vietnam Leadership Trip 2026",
            organizing_company_name="Bluechip",
            support_contacts=support,
            message_content=WELCOME_DEFAULT_MESSAGE_CONTENT,
        )

        self.assertTrue(rendered.startswith("Dear Aarav Sharma,"))
        self.assertIn('group "Vietnam Leadership Trip 2026"', rendered)
        self.assertIn("organised by Bluechip", rendered)
        self.assertIn(
            "All further information, important updates, and arrangements regarding your trip "
            "will be shared with you here.",
            rendered,
        )
        self.assertIn("Replies to this WhatsApp message are not monitored", rendered)
        self.assertIn("Yogesh Kumar Vashistha: +91 98187 52221", rendered)
        self.assertTrue(rendered.endswith("Team Global Connect Travels"))

    def test_welcome_template_parameter_order_matches_meta_template(self) -> None:
        header_parameters = template_header_parameters(
            message_type="welcome",
            recipient_name="Aarav Sharma",
        )
        parameters = template_parameters(
            message_type="welcome",
            recipient_name="Aarav Sharma",
            group_name="Vietnam Leadership Trip 2026",
            organizing_company_name="Bluechip",
            support_contacts="- Raman Jha: +91 98187 52221",
            message_content="Please verify your documents.",
        )

        self.assertEqual(header_parameters, ["Aarav Sharma"])
        self.assertEqual(
            parameters,
            [
                "Vietnam Leadership Trip 2026",
                "Bluechip",
                "Please verify your documents.",
                "- Raman Jha: +91 98187 52221",
            ],
        )

    def test_passport_template_parameter_order_includes_link_and_editable_content(self) -> None:
        self.assertEqual(
            template_header_parameters(
                message_type="passport_link",
                recipient_name="Aarav Sharma",
            ),
            ["Aarav Sharma"],
        )
        parameters = template_parameters(
            message_type="passport_link",
            recipient_name="Aarav Sharma",
            group_name="Vietnam Leadership Trip 2026",
            organizing_company_name="Bluechip",
            passport_link="https://travel.example/upload/abc",
            support_contacts="- Raman Jha: +91 98187 52221",
            message_content=PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT,
        )

        self.assertEqual(parameters[0:3], [
            "Vietnam Leadership Trip 2026",
            "Bluechip",
            "https://travel.example/upload/abc",
        ])
        self.assertEqual(parameters[3], PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT)
        self.assertEqual(parameters[4], "- Raman Jha: +91 98187 52221")

    def test_defaults_are_stable_for_both_actions(self) -> None:
        self.assertEqual(
            default_message_content("welcome"),
            "All further information, important updates, and arrangements regarding your trip "
            "will be shared with you here.",
        )
        self.assertEqual(
            default_message_content("passport_link"),
            PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT,
        )


if __name__ == "__main__":
    unittest.main()
