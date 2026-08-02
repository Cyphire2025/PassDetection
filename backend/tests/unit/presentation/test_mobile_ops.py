from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.core.security.mobile_jwt import MobileAccessClaims
from app.presentation.api.v1.routes.mobile_ops import (
    _accessible_group_ids,
    _attendance_rejection_code,
    _attendance_replay_state,
    _push_fernet,
    _safe_public_payload,
    apply_mobile_attendance_actions,
    create_mobile_incident,
    router,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileAttendanceActionInput,
    MobileAttendanceBatchRequest,
    MobileIncidentCreateRequest,
    MobilePushRegistrationRequest,
)


def _claims(role: str = "coordinator") -> MobileAccessClaims:
    return MobileAccessClaims(
        principal_id=uuid.uuid4(),
        principal_type=role,  # type: ignore[arg-type]
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session_generation=1,
        password_change_required=False,
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
    )


def _action(*, event_id: uuid.UUID | None = None) -> MobileAttendanceActionInput:
    return MobileAttendanceActionInput(
        client_event_id=event_id or uuid.uuid4(),
        signed_qr="pdatt:" + ("A" * 43),
        scanned_at=datetime.now(tz=UTC),
        source="qr",
    )


def test_mobile_ops_routes_match_native_client_contract() -> None:
    assert {route.path for route in router.routes} == {
        "/coordinator/groups/{group_id}/passengers",
        "/coordinator/groups/{group_id}/passengers/{passenger_id}",
        "/coordinator/groups/{group_id}/attendance/sessions",
        "/coordinator/groups/{group_id}/attendance/sessions/{session_id}",
        "/coordinator/groups/{group_id}/attendance/sessions/{session_id}/complete",
        "/coordinator/groups/{group_id}/attendance/actions",
        "/coordinator/groups/{group_id}/attendance/summary",
        "/coordinator/groups/{group_id}/incidents",
        "/push/register",
        "/push/unregister",
        "/notifications",
        "/notifications/{notification_id}/read",
    }


def test_attendance_batch_requires_unique_uuid_event_ids() -> None:
    event_id = uuid.uuid4()
    with pytest.raises(ValidationError, match="must be unique"):
        MobileAttendanceBatchRequest(
            actions=[_action(event_id=event_id), _action(event_id=event_id)]
        )


def test_attendance_scan_timestamp_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        MobileAttendanceActionInput(
            client_event_id=uuid.uuid4(),
            signed_qr="pdatt:" + ("A" * 43),
            scanned_at=datetime.now(),
        )


@pytest.mark.asyncio
async def test_attendance_batch_returns_per_item_idempotent_results() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    actions = [_action(), _action(), _action()]
    attendance_session = SimpleNamespace(
        id=uuid.uuid4(),
        status="active",
        started_at=None,
        completed_at=None,
    )
    passenger = SimpleNamespace(id=uuid.uuid4())

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
            new=AsyncMock(return_value=SimpleNamespace(access=SimpleNamespace())),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._attendance_session_for_action",
            new=AsyncMock(return_value=attendance_session),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._resolve_scannable_passenger",
            new=AsyncMock(
                side_effect=[
                    (passenger, SimpleNamespace(), None),
                    (passenger, SimpleNamespace(), None),
                    (None, None, "wrong_group"),
                ]
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._insert_canonical_attendance_record",
            new=AsyncMock(side_effect=[uuid.uuid4(), None]),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._attendance_replay_state",
            new=AsyncMock(return_value="already_applied"),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.append_mobile_sync_change",
            new=AsyncMock(),
        ),
    ):
        response = await apply_mobile_attendance_actions(
            group_id=group_id,
            body=MobileAttendanceBatchRequest(actions=actions),
            claims=claims,
            session=MagicMock(),
        )

    assert [item.client_event_id for item in response.results] == [
        item.client_event_id for item in actions
    ]
    assert [item.status for item in response.results] == [
        "accepted",
        "already_applied",
        "rejected",
    ]
    assert response.results[-1].reason_code == "QR_WRONG_GROUP"


@pytest.mark.asyncio
async def test_attendance_replay_rejects_event_id_bound_to_another_passenger() -> None:
    claims = _claims()
    requested_passenger = uuid.uuid4()
    reused_event_id = str(uuid.uuid4())
    result = MagicMock()
    result.all.return_value = [
        SimpleNamespace(
            passenger_id=uuid.uuid4(),
            client_event_id=reused_event_id,
        )
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    state = await _attendance_replay_state(
        session,
        claims=claims,
        attendance_session=SimpleNamespace(id=uuid.uuid4()),
        passenger_id=requested_passenger,
        client_event_id=reused_event_id,
    )

    assert state == "event_reused"
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "attendance_records.agency_id" in sql
    assert "attendance_session_family.canonical_session_id" in sql
    assert reused_event_id in sql


def test_attendance_rejection_codes_do_not_echo_internal_values() -> None:
    assert _attendance_rejection_code("expired") == "QR_EXPIRED"
    assert _attendance_rejection_code("database-details") == "QR_INVALID"


def test_push_token_ciphertext_does_not_contain_plaintext() -> None:
    token = b"ExponentPushToken[private-device-token]"
    encrypted = _push_fernet().encrypt(token)
    assert token not in encrypted
    assert _push_fernet().decrypt(encrypted) == token


def test_push_token_is_trimmed_before_length_validation() -> None:
    with pytest.raises(ValidationError):
        MobilePushRegistrationRequest(
            provider="fcm",
            push_token=" " * 16,
            installation_id="installation-1234",
        )

    request = MobilePushRegistrationRequest(
        provider="fcm",
        push_token="  valid-push-token-1234  ",
        installation_id="installation-1234",
    )
    assert request.push_token == "valid-push-token-1234"


def test_notification_payload_uses_a_fixed_public_allowlist() -> None:
    safe = _safe_public_payload(
        {
            "screen": "updates",
            "group_id": str(uuid.uuid4()),
            "passport_number": "P1234567",
            "storage_key": "private/passport.pdf",
        }
    )
    assert set(safe) == {"screen", "group_id"}


def test_accessible_notification_groups_are_role_and_tenant_scoped() -> None:
    claims = _claims("client_manager")
    statement = _accessible_group_ids(claims, datetime.now(tz=UTC))
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "gc_group_access.is_enabled IS true" in sql
    assert "gc_group_access.client_manager_access_enabled IS true" in sql
    assert "client_manager_profiles.user_id" in sql
    assert claims.principal_id.hex in sql
    assert claims.agency_id.hex in sql
    assert "client_manager_group_assignments.is_active IS true" in sql
    assert "client_manager_group_assignments.revoked_at IS NULL" in sql


@pytest.mark.asyncio
async def test_incident_retry_returns_durable_receipt_without_duplicate_insert() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    body = MobileIncidentCreateRequest(
        client_event_id=uuid.uuid4(),
        title="Transport delay",
        description="The airport transfer is delayed by twenty minutes.",
        severity="medium",
        occurred_at=datetime.now(tz=UTC),
    )
    request_hash = hashlib.sha256(
        json.dumps(
            body.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    insert_result = MagicMock()
    insert_result.scalar_one_or_none.return_value = None
    receipt = SimpleNamespace(
        request_hash=request_hash,
        status="completed",
        resource_id=incident_id,
    )
    receipt_result = MagicMock()
    receipt_result.scalar_one_or_none.return_value = receipt
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[insert_result, receipt_result])
    request = MagicMock(client=None)

    with patch(
        "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
        new=AsyncMock(return_value=SimpleNamespace(access=SimpleNamespace(id=uuid.uuid4()))),
    ):
        response = await create_mobile_incident(
            group_id=group_id,
            body=body,
            request=request,
            claims=claims,
            session=session,
        )

    assert response.status == "already_applied"
    assert response.incident_id == incident_id
    assert session.execute.await_count == 2
