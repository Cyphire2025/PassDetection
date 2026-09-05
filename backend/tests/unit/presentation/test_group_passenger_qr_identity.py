from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.presentation.api.v1.routes.tour_operations_qr_helpers import group_passenger_qr_codes


async def test_each_roster_row_exposes_only_its_own_qr_payload() -> None:
    now = datetime.now(tz=UTC)
    passengers = [
        SimpleNamespace(
            id=uuid.uuid4(),
            client_name=f"Traveller {index}",
            client_email=None,
            client_phone=None,
            departure_city=None,
        )
        for index in range(2)
    ]
    tokens = [
        SimpleNamespace(
            passenger_id=passenger.id,
            qr_payload=f"pdatt:synthetic-{index}",
            is_active=True,
            token_version=1,
            created_at=now,
            expires_at=now + timedelta(days=2),
            revoked_at=None,
        )
        for index, passenger in enumerate(passengers)
    ]
    passenger_result = Mock()
    passenger_result.all.return_value = [(passenger,) for passenger in passengers]
    token_result = Mock()
    token_result.scalars.return_value.all.return_value = tokens
    session = Mock(execute=AsyncMock(side_effect=[passenger_result, token_result]))
    result = await group_passenger_qr_codes(
        session, uuid.uuid4(), SimpleNamespace(id=uuid.uuid4(), name="Synthetic group")
    )
    assert [(row.passenger_id, row.qr_payload) for row in result.passengers] == [
        (passenger.id, token.qr_payload)
        for passenger, token in zip(passengers, tokens, strict=True)
    ]
    assert result.passengers[0].qr_payload != result.passengers[1].qr_payload
