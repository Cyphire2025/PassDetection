"""Regression tests for editable WhatsApp message-content semantics."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException

from app.application.use_cases.whatsapp.message_templates import (
    PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT,
)
from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes.whatsapp import (
    _resolve_message_content,
    _resolve_send_message_content,
    create_broadcast_group,
)
from tests.route_dependencies import patch_route_dependency


class WhatsAppMessageContentTests(unittest.TestCase):
    def test_none_uses_the_initial_welcome_copy(self) -> None:
        self.assertEqual(
            _resolve_message_content(
                "welcome",
                None,
                group_name="Thailand",
            ),
            'This message is regarding your upcoming trip to "Thailand".',
        )

    def test_explicitly_cleared_content_remains_empty_for_preview(self) -> None:
        self.assertEqual(
            _resolve_message_content("welcome", "", group_name="Thailand"),
            "",
        )
        self.assertEqual(
            _resolve_message_content("welcome", "   ", group_name="Thailand"),
            "",
        )

    def test_passport_none_uses_exact_approved_instruction_copy(self) -> None:
        self.assertEqual(
            _resolve_message_content(
                "passport_link",
                None,
                group_name="Thailand",
            ),
            PASSPORT_LINK_DEFAULT_MESSAGE_CONTENT,
        )

    def test_empty_content_is_rejected_when_sending(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            _resolve_send_message_content(
                "welcome",
                "   ",
                group_name="Thailand",
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("Meta requires this template field", raised.exception.detail)


class WhatsAppCreateGroupCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_without_organizing_company_persists_legacy_empty_value(self) -> None:
        session = MagicMock()
        session.flush = AsyncMock()
        session.rollback = AsyncMock()
        current_user = SimpleNamespace(
            id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            role=UserRole.AGENCY_ADMIN,
        )
        actor = SimpleNamespace(id=current_user.id, agency_id=current_user.agency_id)

        async def return_group(_session: object, group: object) -> object:
            return group

        with (
            patch_route_dependency(
                "app.presentation.api.v1.routes.whatsapp._group_detail",
                new=AsyncMock(side_effect=return_group),
            ),
            patch_route_dependency(
                "app.presentation.api.v1.routes.whatsapp._lock_active_whatsapp_actor",
                new=AsyncMock(return_value=actor),
            ),
        ):
            created = await create_broadcast_group(
                name="Thailand Delegates",
                organizing_company_name=None,
                contacts_json=('[{"name":"Aarav Sharma","phone_number":"+91 98765 43210"}]'),
                rejected_contacts_json="[]",
                support_contacts_json=(
                    '[{"name":"Support Desk","phone_number":"+91 98765 43211"}]'
                ),
                recipient_opt_in_confirmed=True,
                contacts_file=None,
                current_user=current_user,
                session=session,
            )

        self.assertEqual(created.organizing_company_name, "")
        self.assertEqual(created.name, "Thailand Delegates")


if __name__ == "__main__":
    unittest.main()
