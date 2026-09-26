"""Preserve passenger fields and QR lifecycle while splitting transport owners."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import PassportSubmissionModel
from app.presentation.api.v1.routes import tour_operations_assignments as assignments
from app.presentation.api.v1.routes import tour_operations_passenger_views as views
from app.presentation.api.v1.routes import tour_operations_qr as qr
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    SetPassengerQrActiveRequest,
    SetPassengerQrExpirationRequest,
)


def _actor():
    return User.create(
        email="owner@example.com",
        hashed_password="unused",
        full_name="Owner",
        role=UserRole.AGENCY_COORDINATOR,
        agency_id=uuid.uuid4(),
    )


@pytest.mark.parametrize("family_count", [0, 1, 2, 3])
async def test_office_and_coordinator_passenger_projections_keep_fields_and_hide_qr(
    monkeypatch, family_count
):
    actor = _actor()
    group_id = uuid.uuid4()
    family_id = uuid.uuid4() if family_count else None
    passengers = [
        PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=actor.agency_id,
            group_id=group_id,
            client_name=f"Person {index}",
            client_email="person@example.com",
            client_phone="+919999999999",
            departure_city="Mumbai",
            submission_mode="family" if family_count else "single",
            family_group_id=family_id,
            family_member_index=index if family_count else None,
            family_relation="child",
            family_gender="female",
            family_head_name="Family head" if family_count else None,
            status="submitted",
            image_s3_key="synthetic/front",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            confirmed_fields={"passport_number": "SYNTHETIC"},
            overall_confidence=0.91,
        )
        for index in range(max(1, family_count))
    ]
    row_result = Mock(
        all=Mock(return_value=[(row, actor.id, actor.full_name) for row in passengers])
    )
    office_session = Mock(execute=AsyncMock(return_value=row_result))
    office = await views._group_passenger_responses(office_session, actor.agency_id, group_id)
    monkeypatch.setattr(assignments, "_ensure_group_assigned_to_coordinator", AsyncMock())
    coordinator_session = Mock(
        execute=AsyncMock(
            return_value=Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=passengers))))
        )
    )
    coordinator = await assignments.list_my_group_passengers(group_id, actor, coordinator_session)
    assert len(coordinator) == len(office) == max(1, family_count)
    for actual, expected in zip(coordinator, office, strict=True):
        assert actual.model_dump(
            exclude={"coordinator_id", "coordinator_name"}
        ) == expected.model_dump(exclude={"coordinator_id", "coordinator_name"})
        assert actual.coordinator_id is None and expected.coordinator_id == actor.id
        assert actual.family_size == max(1, family_count)
        assert actual.qr_payload is None
        assert actual.family_gender == "female" and actual.departure_city == "Mumbai"
    detail_session = Mock(
        execute=AsyncMock(return_value=Mock(scalar_one_or_none=Mock(return_value=passengers[0])))
    )
    detail = await assignments.get_my_group_passenger_detail(
        group_id, passengers[0].id, actor, detail_session
    )
    assert detail.id == passengers[0].id and detail.qr_payload is None
    assert detail.passport_fields == {"passport_number": "SYNTHETIC"}
    assert detail.overall_confidence == 0.91 and detail.family_size == 1  # existing detail contract


@pytest.mark.parametrize("operation", ["generate", "regenerate", "revoke", "active", "expiration"])
async def test_qr_mutation_preserves_scope_audit_and_token_lifecycle(monkeypatch, operation):
    actor = _actor()
    group_id, passenger_id = uuid.uuid4(), uuid.uuid4()
    group = SimpleNamespace(id=group_id)
    token = SimpleNamespace(
        id=uuid.uuid4(),
        passenger_id=passenger_id,
        token_version=3,
        is_active=True,
        qr_payload="GCQR1:" + "a" * 43,
        revoked_at=None,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    scope = AsyncMock(return_value=group)
    passenger = AsyncMock()
    audit = AsyncMock()
    issue = AsyncMock(return_value=(token, token.qr_payload))
    monkeypatch.setattr(qr, "_get_manageable_group", scope)
    monkeypatch.setattr(qr, "_get_qr_passenger", passenger)
    monkeypatch.setattr(qr, "_latest_passenger_qr", AsyncMock(return_value=token))
    monkeypatch.setattr(qr, "_issue_passenger_qr", issue)
    monkeypatch.setattr(qr, "_record_qr_audit", audit)
    session = Mock(execute=AsyncMock(), flush=AsyncMock())
    request = Mock()
    if operation in {"generate", "regenerate", "revoke"}:
        result = await getattr(qr, f"{operation}_passenger_qr")(
            group_id, passenger_id, request, actor, session
        )
    elif operation == "active":
        result = await qr.set_passenger_qr_active(
            group_id,
            passenger_id,
            SetPassengerQrActiveRequest(is_active=False),
            request,
            actor,
            session,
        )
    else:
        result = await qr.set_passenger_qr_expiration(
            group_id,
            passenger_id,
            SetPassengerQrExpirationRequest(expires_at=datetime.now(UTC) - timedelta(seconds=1)),
            request,
            actor,
            session,
        )
    scope.assert_awaited_once_with(session, actor.agency_id, group_id, actor)
    passenger.assert_awaited_once_with(session, actor.agency_id, group_id, passenger_id)
    assert result.passenger_id == passenger_id and result.token_version == 3
    assert audit.await_args.kwargs["passenger_id"] == passenger_id
    assert audit.await_args.kwargs["metadata"]["group_id"] == str(group_id)
    if operation in {"generate", "regenerate"}:
        assert result.qr_payload == token.qr_payload
        assert issue.await_args.kwargs["regenerate"] is (operation == "regenerate")
    elif operation in {"revoke", "expiration"}:
        assert token.is_active is False and result.qr_payload is None
        assert (token.revoked_at is not None) is (operation == "revoke")
    else:
        assert result.status == "inactive" and token.is_active is False


@pytest.mark.parametrize("state", ["missing", "revoked", "expired"])
async def test_invalid_qr_activation_never_updates_or_audits(monkeypatch, state):
    actor = _actor()
    token = (
        None
        if state == "missing"
        else SimpleNamespace(
            revoked_at=datetime.now(UTC) if state == "revoked" else None,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    monkeypatch.setattr(qr, "_get_manageable_group", AsyncMock())
    monkeypatch.setattr(qr, "_get_qr_passenger", AsyncMock())
    monkeypatch.setattr(qr, "_latest_passenger_qr", AsyncMock(return_value=token))
    audit = AsyncMock()
    monkeypatch.setattr(qr, "_record_qr_audit", audit)
    session = Mock(execute=AsyncMock(), flush=AsyncMock())
    with pytest.raises(HTTPException) as failure:
        await qr.set_passenger_qr_active(
            uuid.uuid4(),
            uuid.uuid4(),
            SetPassengerQrActiveRequest(is_active=True),
            Mock(),
            actor,
            session,
        )
    assert failure.value.status_code == (404 if state == "missing" else 409)
    session.execute.assert_not_awaited()
    session.flush.assert_not_awaited()
    audit.assert_not_awaited()
