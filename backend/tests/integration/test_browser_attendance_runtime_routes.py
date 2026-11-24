"""Actual browser runtime HTTP policy with synthetic durable sessions and rows."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from http.cookies import SimpleCookie

import pytest
from sqlalchemy import select

from app.infrastructure.database.models import (
    AttendanceRuntimeRegistrationModel,
    AuditLogModel,
    UserModel,
)
from app.presentation.security.auth_cookies import (
    ATTENDANCE_RUNTIME_COOKIE_NAME,
    ATTENDANCE_RUNTIME_COOKIE_PATH,
)
from tests.dashboard_session_fixtures import issue_dashboard_access
from tests.integration.test_browser_attendance_discard_atomicity import (
    _cohort,
    _commit_requests,
)
from tests.integration.test_browser_attendance_discard_atomicity import (
    _sqlite_named_conflict_targets as _sqlite_named_conflict_targets,
)

ENDPOINT = "/api/v1/tour-operations/coordinator/attendance/runtime"


def _headers(f, *, cookie=False):
    headers = {"Authorization": f"Bearer {f.access}"}
    if cookie:
        headers["Cookie"] = f"{ATTENDANCE_RUNTIME_COOKIE_NAME}=v1.pwa.{f.secret}"
    return headers


@pytest.mark.parametrize(
    "kind,existing,expected",
    [("pwa", False, "registered"), ("pwa", True, "renewed"), ("webview", True, "replaced")],
)
async def test_runtime_registration_cookie_and_current_persisted_state(
    client, db_session, monkeypatch, kind, existing, expected
):
    f = await _cohort(db_session)
    _commit_requests(client, db_session, monkeypatch)
    response = await client.post(
        ENDPOINT, headers=_headers(f, cookie=existing), json={"runtime_kind": kind}
    )
    assert response.status_code == 201, response.text
    result = response.json()
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    current = cookie[ATTENDANCE_RUNTIME_COOKIE_NAME]
    assert current["httponly"] and current["samesite"] == "strict"
    assert current["path"] == ATTENDANCE_RUNTIME_COOKIE_PATH
    assert current["max-age"] and int(current["max-age"]) > 0
    assert current.value.startswith(f"v1.{kind}.")
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    runtime_id = uuid.UUID(result["runtime_id"])
    assert (runtime_id == f.runtime) == (expected == "renewed")
    db_session.expire_all()
    row = await db_session.get(AttendanceRuntimeRegistrationModel, runtime_id)
    assert row.status == "active" and row.runtime_kind == kind
    assert row.runtime_identifier_hash != current.value.rsplit(".", 1)[1]
    original = await db_session.get(AttendanceRuntimeRegistrationModel, f.runtime)
    assert original.status == ("replaced" if expected == "replaced" else "active")
    if expected == "replaced":
        assert original.replaced_by_runtime_id == runtime_id and original.revoked_at is not None
    audit = (await db_session.scalars(select(AuditLogModel))).one()
    assert audit.metadata_json["outcome"] == expected
    assert current.value not in repr(audit.metadata_json)


async def test_coordinator_revoke_clears_exact_cookie_and_keeps_revoked_registration(
    client, db_session, monkeypatch
):
    f = await _cohort(db_session)
    _commit_requests(client, db_session, monkeypatch)
    response = await client.delete(ENDPOINT, headers=_headers(f, cookie=True))
    assert response.status_code == 204 and response.content == b""
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    assert cookie[ATTENDANCE_RUNTIME_COOKIE_NAME]["max-age"] == "0"
    assert cookie[ATTENDANCE_RUNTIME_COOKIE_NAME]["path"] == ATTENDANCE_RUNTIME_COOKIE_PATH
    db_session.expire_all()
    row = await db_session.get(AttendanceRuntimeRegistrationModel, f.runtime)
    assert row.status == "revoked" and row.revoked_at is not None
    denied = await client.delete(ENDPOINT, headers=_headers(f, cookie=True))
    assert denied.status_code == 428


@pytest.mark.parametrize("foreign_coordinator", [False, True])
async def test_manager_disposition_is_mfa_and_exact_coordinator_scoped(
    client, db_session, monkeypatch, foreign_coordinator
):
    f = await _cohort(db_session)
    manager_id = uuid.uuid4()
    db_session.add(
        UserModel(
            id=manager_id,
            agency_id=f.agency,
            email=f"{manager_id}@example.test",
            full_name="Synthetic manager",
            hashed_password="unused",
            role="agency_manager",
        )
    )
    await db_session.flush()
    access, _ = await issue_dashboard_access(
        db_session,
        user_id=manager_id,
        agency_id=f.agency,
        role="agency_manager",
        authentication_methods=("pwd", "totp"),
        mfa_authenticated_at=datetime.now(UTC),
    )
    await db_session.commit()
    _commit_requests(client, db_session, monkeypatch)
    endpoint = f"/api/v1/tour-operations/attendance/runtimes/{f.runtime}/status"
    response = await client.patch(
        endpoint,
        headers={"Authorization": f"Bearer {access}"},
        json={
            "coordinator_user_id": str(uuid.uuid4() if foreign_coordinator else f.actor),
            "status": "lost",
            "reason": "Synthetic lost device",
        },
    )
    assert response.status_code == (404 if foreign_coordinator else 200), response.text
    db_session.expire_all()
    runtime = await db_session.get(AttendanceRuntimeRegistrationModel, f.runtime)
    assert runtime.status == ("active" if foreign_coordinator else "lost")
    rows = list((await db_session.scalars(select(AuditLogModel))).all())
    assert len(rows) == int(not foreign_coordinator)
    if rows:
        assert rows[0].metadata_json["reason_category"] == "manager_runtime_disposition"
        assert "Synthetic lost device" not in repr(rows[0].metadata_json)


async def test_manager_without_recent_mfa_cannot_dispose_runtime(client, db_session, monkeypatch):
    f = await _cohort(db_session)
    manager_id = uuid.uuid4()
    db_session.add(
        UserModel(
            id=manager_id,
            agency_id=f.agency,
            email=f"{manager_id}@example.test",
            full_name="Synthetic manager",
            hashed_password="unused",
            role="agency_manager",
        )
    )
    await db_session.flush()
    access, _ = await issue_dashboard_access(
        db_session, user_id=manager_id, agency_id=f.agency, role="agency_manager"
    )
    await db_session.commit()
    _commit_requests(client, db_session, monkeypatch)
    response = await client.patch(
        f"/api/v1/tour-operations/attendance/runtimes/{f.runtime}/status",
        headers={"Authorization": f"Bearer {access}"},
        json={
            "coordinator_user_id": str(f.actor),
            "status": "lost",
            "reason": "Synthetic lost device",
        },
    )
    assert response.status_code == 403, response.text
    db_session.expire_all()
    assert (await db_session.get(AttendanceRuntimeRegistrationModel, f.runtime)).status == "active"
    assert not (await db_session.scalars(select(AuditLogModel))).all()
