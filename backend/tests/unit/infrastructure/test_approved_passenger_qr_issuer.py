"""Unit checks for approved-only idempotent QR issuance."""

from __future__ import annotations

import unittest
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.infrastructure.qr.approved_passenger_qr_issuer import (
    ensure_approved_passenger_qr,
    ensure_approved_passenger_qrs,
    ensure_mobile_passenger_qr,
)


class ApprovedPassengerQrIssuerTests(unittest.IsolatedAsyncioTestCase):
    async def test_mobile_issuer_creates_qr_without_dashboard_render_step(self) -> None:
        agency_id = uuid.uuid4()
        group_id = uuid.uuid4()
        passenger = SimpleNamespace(id=uuid.uuid4(), agency_id=agency_id, status="submitted")
        group = SimpleNamespace(
            id=group_id,
            agency_id=agency_id,
            return_date=None,
            created_by_user_id=uuid.uuid4(),
        )
        row_result = Mock()
        row_result.first.return_value = (passenger, group)
        token_result = Mock()
        token_result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.add = Mock()
        session.execute.side_effect = [row_result, token_result]

        token = await ensure_mobile_passenger_qr(
            session,
            agency_id=agency_id,
            group_id=group_id,
            passenger_id=passenger.id,
        )

        self.assertIsNotNone(token)
        self.assertTrue(token.qr_payload.startswith("pdatt:"))
        session.add.assert_called_once_with(token)
        session.flush.assert_awaited_once()

    async def test_mobile_issuer_reuses_current_usable_qr(self) -> None:
        agency_id = uuid.uuid4()
        group_id = uuid.uuid4()
        passenger = SimpleNamespace(id=uuid.uuid4(), agency_id=agency_id, status="submitted")
        group = SimpleNamespace(
            id=group_id,
            agency_id=agency_id,
            return_date=None,
            created_by_user_id=uuid.uuid4(),
        )
        existing = SimpleNamespace(
            qr_payload="pdatt:opaque",
            is_active=True,
            revoked_at=None,
            expires_at=datetime.now(tz=UTC) + timedelta(days=1),
            token_version=3,
        )
        row_result = Mock()
        row_result.first.return_value = (passenger, group)
        token_result = Mock()
        token_result.scalar_one_or_none.return_value = existing
        session = AsyncMock()
        session.add = Mock()
        session.execute.side_effect = [row_result, token_result]

        token = await ensure_mobile_passenger_qr(
            session,
            agency_id=agency_id,
            group_id=group_id,
            passenger_id=passenger.id,
        )

        self.assertIs(token, existing)
        session.add.assert_not_called()
        session.flush.assert_not_awaited()

    async def test_bulk_issuer_reuses_existing_and_creates_missing_tokens(self) -> None:
        group = SimpleNamespace(return_date=None, created_by_user_id=uuid.uuid4())
        existing_passenger = SimpleNamespace(
            id=uuid.uuid4(), agency_id=uuid.uuid4(), status="staff_approved"
        )
        new_passenger = SimpleNamespace(
            id=uuid.uuid4(), agency_id=uuid.uuid4(), status="staff_approved"
        )
        existing_token = SimpleNamespace(
            passenger_id=existing_passenger.id,
            token_version=1,
        )
        row_result = Mock()
        row_result.all.return_value = [
            (existing_passenger, group),
            (new_passenger, group),
        ]
        token_result = Mock()
        token_result.scalars.return_value.all.return_value = [existing_token]
        session = AsyncMock()
        session.add = Mock()
        session.execute.side_effect = [row_result, token_result]

        tokens = await ensure_approved_passenger_qrs(
            session,
            [new_passenger.id, existing_passenger.id, new_passenger.id],
        )

        self.assertEqual(len(tokens), 2)
        self.assertIs(tokens[0], existing_token)
        self.assertEqual(tokens[1].passenger_id, new_passenger.id)
        session.add.assert_called_once_with(tokens[1])
        session.flush.assert_awaited_once()

    async def test_ai_approved_passenger_receives_one_idempotent_token(self) -> None:
        passenger = SimpleNamespace(
            id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            status="ai_approved",
        )
        group = SimpleNamespace(return_date=None, created_by_user_id=uuid.uuid4())
        row_result = Mock()
        row_result.first.return_value = (passenger, group)
        token_result = Mock()
        token_result.scalar_one_or_none.return_value = None
        session = AsyncMock()
        session.add = Mock()
        session.execute.side_effect = [row_result, token_result]

        token = await ensure_approved_passenger_qr(session, passenger.id)

        self.assertIsNotNone(token)
        self.assertEqual(token.passenger_id, passenger.id)
        self.assertTrue(token.qr_payload.startswith("pdatt:"))
        session.add.assert_called_once_with(token)
        session.flush.assert_awaited_once()

    async def test_submitted_passenger_never_receives_a_token(self) -> None:
        passenger = SimpleNamespace(
            id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            status="submitted",
        )
        group = SimpleNamespace(return_date=None, created_by_user_id=uuid.uuid4())
        row_result = Mock()
        row_result.first.return_value = (passenger, group)
        session = AsyncMock()
        session.add = Mock()
        session.execute.return_value = row_result

        token = await ensure_approved_passenger_qr(session, passenger.id)

        self.assertIsNone(token)
        session.add.assert_not_called()

    async def test_existing_token_is_returned_without_creating_another(self) -> None:
        passenger = SimpleNamespace(
            id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            status="ai_approved",
        )
        group = SimpleNamespace(return_date=None, created_by_user_id=uuid.uuid4())
        existing = SimpleNamespace(passenger_id=passenger.id, token_version=1)
        row_result = Mock()
        row_result.first.return_value = (passenger, group)
        token_result = Mock()
        token_result.scalar_one_or_none.return_value = existing
        session = AsyncMock()
        session.add = Mock()
        session.execute.side_effect = [row_result, token_result]

        token = await ensure_approved_passenger_qr(session, passenger.id)

        self.assertIs(token, existing)
        session.add.assert_not_called()
        session.flush.assert_not_awaited()
