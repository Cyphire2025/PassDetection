"""Regression tests for editable WhatsApp message-content semantics."""

from __future__ import annotations

import unittest

from fastapi import HTTPException

from app.application.use_cases.whatsapp.message_templates import (
    WELCOME_DEFAULT_MESSAGE_CONTENT,
)
from app.presentation.api.v1.routes.whatsapp import (
    _resolve_message_content,
    _resolve_send_message_content,
)


class WhatsAppMessageContentTests(unittest.TestCase):
    def test_none_uses_the_initial_welcome_copy(self) -> None:
        self.assertEqual(
            _resolve_message_content("welcome", None),
            WELCOME_DEFAULT_MESSAGE_CONTENT,
        )

    def test_explicitly_cleared_content_remains_empty_for_preview(self) -> None:
        self.assertEqual(_resolve_message_content("welcome", ""), "")
        self.assertEqual(_resolve_message_content("welcome", "   "), "")

    def test_empty_content_is_rejected_when_sending(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            _resolve_send_message_content("welcome", "   ")

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Meta requires this template field", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
