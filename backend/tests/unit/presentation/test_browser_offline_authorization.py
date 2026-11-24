"""Public browser facade keeps signed-roster admission and call-time services."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException, Request, Response
from sqlalchemy.dialects import postgresql

from app.core.security.mobile_offline_lease import sign_offline_manifest
from app.domain.entities.entities import User, UserRole
from app.presentation.api.v1.routes import attendance_runtime as routes


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class _Session:
    def __init__(self, group, activities, passengers, count):
        self.scalars = iter([group, count])
        self.results = iter([activities, passengers])
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return next(self.scalars)

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(next(self.results))


@pytest.fixture
def offline_context(monkeypatch, test_settings):
    now = datetime.now(UTC)
    agency, group, actor, activity, passenger = (uuid.uuid4() for _ in range(5))
    user = User(
        id=actor,
        agency_id=agency,
        email="synthetic@example.test",
        full_name="Synthetic coordinator",
        hashed_password="unused",
        role=UserRole.AGENCY_COORDINATOR,
    )
    activity_row = SimpleNamespace(
        id=activity,
        name="Synthetic boarding",
        scheduled_starts_at=now - timedelta(minutes=5),
        scheduled_ends_at=now + timedelta(hours=1),
    )
    passenger_row = SimpleNamespace(
        id=passenger,
        client_name="Synthetic passenger",
        token_hash="b" * 64,
        token_version=2,
        expires_at=now + timedelta(days=1),
    )
    audit = SimpleNamespace(record=AsyncMock())
    ensure = AsyncMock()
    runtime = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    revision = AsyncMock(return_value=42)
    monkeypatch.setattr(routes, "get_settings", lambda: test_settings)
    monkeypatch.setattr(routes, "resolve_browser_attendance_runtime", runtime)
    monkeypatch.setattr(routes, "_ensure_group_assigned_to_coordinator", ensure)
    monkeypatch.setattr(routes, "coordinator_roster_revision", revision)
    monkeypatch.setattr(routes, "AuditLogRepository", lambda _session: audit)
    monkeypatch.setattr(
        routes,
        "sign_offline_manifest",
        lambda payload: sign_offline_manifest(payload, settings=test_settings.mobile),
    )
    return SimpleNamespace(
        now=now,
        agency=agency,
        group=group,
        user=user,
        activity=activity_row,
        passenger=passenger_row,
        audit=audit,
        ensure=ensure,
        runtime=runtime,
        revision=revision,
        group_row=SimpleNamespace(id=group, name="Synthetic trip"),
    )


async def _provision(f, *, activities=None, passengers=None, count=1, group=True):
    session = _Session(
        f.group_row if group else None,
        [f.activity] if activities is None else activities,
        [f.passenger] if passengers is None else passengers,
        count,
    )
    response = Response()
    result = await routes.provision_browser_offline_authorization(
        f.group,
        Request({"type": "http", "method": "GET", "path": "/", "headers": []}),
        response,
        current_user=f.user,
        session=session,
    )
    return result, response, session


def _decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


async def test_original_facade_signs_minimal_bounded_roster_with_current_services(offline_context):
    f = offline_context
    result, response, session = await _provision(f)
    payload_bytes = _decode(result.payload)
    Ed25519PublicKey.from_public_bytes(_decode(result.public_key)).verify(
        _decode(result.signature), payload_bytes
    )
    payload = json.loads(payload_bytes)
    assert payload["coordinator_user_id"] == str(f.user.id)
    assert payload["tenant_id"] == str(f.agency) and payload["group_id"] == str(f.group)
    assert payload["roster_revision"] == 42
    assert payload["passengers"] == [
        {
            "id": str(f.passenger.id),
            "label": "Synthetic passenger",
            "token_hash": "b" * 64,
            "token_version": 2,
            "token_valid_until": f.passenger.expires_at.isoformat().replace("+00:00", "Z"),
        }
    ]
    assert [item["id"] for item in payload["sessions"]] == [str(f.activity.id)]
    assert (
        datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
        <= f.activity.scheduled_ends_at
    )
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    f.ensure.assert_awaited_once_with(session, f.agency, f.group, f.user.id)
    f.runtime.assert_awaited_once()
    assert f.runtime.await_args.kwargs["required"] is True
    f.revision.assert_awaited_once_with(session, agency_id=f.agency, group_id=f.group)
    assert len(session.statements) == 4
    sql = "\n".join(
        str(stmt.compile(dialect=postgresql.dialect())).lower() for stmt in session.statements
    )
    assert "limit" in sql and "passenger_qr_tokens.agency_id" in sql
    assert not any(
        field in sql
        for field in ("client_phone", "client_email", "image_s3_key", "extracted_fields")
    )
    metadata = f.audit.record.await_args.kwargs["metadata"]
    assert metadata["passenger_count"] == metadata["session_count"] == 1
    assert "Synthetic passenger" not in repr(metadata) and "b" * 64 not in repr(metadata)


@pytest.mark.parametrize(
    "case,code",
    [
        ("no_activity", "OFFLINE_ACTIVITY_NOT_AVAILABLE"),
        ("activity_limit", "OFFLINE_ACTIVITY_LIMIT_EXCEEDED"),
        ("missing_schedule", "ATTENDANCE_SCHEDULE_REQUIRED"),
        ("missing_qr", "OFFLINE_ROSTER_INCOMPLETE"),
        ("empty_roster", "OFFLINE_ROSTER_INCOMPLETE"),
        ("roster_limit", "OFFLINE_ROSTER_LIMIT_EXCEEDED"),
        ("ended_activity", "OFFLINE_ACTIVITY_OUTSIDE_WINDOW"),
    ],
)
async def test_offline_admission_fails_closed_without_signing_or_audit(offline_context, case, code):
    f = offline_context
    changes = {}
    if case == "no_activity":
        changes["activities"] = []
    if case == "activity_limit":
        changes["activities"] = [f.activity] * 201
    if case == "missing_schedule":
        f.activity.scheduled_ends_at = None
    if case == "missing_qr":
        changes["passengers"] = []
    if case == "empty_roster":
        changes.update(passengers=[], count=0)
    if case == "roster_limit":
        changes.update(passengers=[f.passenger] * 2001, count=2001)
    if case == "ended_activity":
        f.activity.scheduled_ends_at = f.now - timedelta(seconds=1)
    with pytest.raises(HTTPException) as denied:
        await _provision(f, **changes)
    assert denied.value.status_code == 409 and denied.value.detail["code"] == code
    assert denied.value.headers["Cache-Control"] == "private, no-store"
    f.revision.assert_not_awaited()
    f.audit.record.assert_not_awaited()


async def test_unassigned_group_denial_stops_before_database_reads(offline_context):
    f = offline_context
    f.ensure.side_effect = HTTPException(status_code=404)
    with pytest.raises(HTTPException) as denied:
        await _provision(f)
    assert denied.value.status_code == 404
    f.audit.record.assert_not_awaited()
    f.revision.assert_not_awaited()
