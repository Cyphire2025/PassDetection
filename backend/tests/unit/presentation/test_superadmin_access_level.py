"""Exercise access selection through signed sessions and real database identities."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import jwt
import pytest
from fastapi import Response
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.core.security.access_level import ACCESS_LEVEL_COOKIE, apply_access_level_cookie
from app.core.security.jwt import create_access_token, decode_access_token
from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import AuthenticationError
from app.infrastructure.database.models import AgencyModel, ClientGroupModel, UserModel
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.security.access_level import set_access_level_cookie


async def _seed(session, client, *, role=UserRole.SUPER_ADMIN, own_agency=False):
    agency = AgencyModel(id=uuid.uuid4(), name="Office", email="office@example.test")
    model = UserModel(
        id=uuid.uuid4(), email="operator@example.test", full_name="Operator",
        hashed_password="unused", role=role.value,
        agency_id=agency.id if own_agency else None,
    )
    session.add_all([agency, model])
    await session.flush()
    user = await UserRepository(session).get_by_id(model.id)
    token, _ = create_access_token(
        user.id, role.value, agency_id=user.agency_id,
        session_expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    client.headers["Authorization"] = "Bearer " + token
    return agency, model, user, token


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["agency_manager", "agency_staff", "agency_coordinator"])
async def test_superadmin_switches_and_restores_without_mfa_or_identity_change(
    db_session, client, role,
):
    agency, model, user, token = await _seed(db_session, client)
    before_claims = decode_access_token(token)
    switched = await client.post("/api/v1/auth/access-level", json={"role": role})
    assert switched.status_code == 200, switched.text
    body = switched.json()
    assert body["id"] == str(user.id)
    assert body["role"] == body["access_level"] == role
    assert body["actual_role"] == "super_admin"
    assert body["can_switch_access_level"] is True
    assert body["agency_id"] == str(agency.id)
    assert body["access_level_agency_name"] == "Office"
    cookies = SimpleCookie()
    for header in switched.headers.get_list("set-cookie"):
        cookies.load(header)
    assert set(cookies) == {ACCESS_LEVEL_COOKIE}
    mode = cookies[ACCESS_LEVEL_COOKIE]
    assert mode["httponly"] and mode["path"] == "/"
    assert mode["max-age"] == mode["expires"] == ""
    selected = jwt.decode(mode.value, get_settings().app_secret_key,
                          algorithms=[get_settings().jwt.algorithm])
    assert selected["exp"] == before_claims["session_exp"]
    assert "mfa_at" not in before_claims
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["role"] == role
    await db_session.refresh(model)
    assert model.role == "super_admin" and model.agency_id is None
    restored = await client.post("/api/v1/auth/access-level", json={"role": "super_admin"})
    assert restored.status_code == 200, restored.text
    assert restored.json()["role"] == "super_admin"
    assert restored.json()["agency_id"] is None
    assert restored.json()["id"] == str(user.id)
    assert (await client.get("/api/v1/auth/me")).json()["role"] == "super_admin"


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER,
                                 UserRole.AGENCY_STAFF, UserRole.AGENCY_COORDINATOR])
async def test_other_accounts_cannot_select_any_access_level(db_session, client, role):
    await _seed(db_session, client, role=role, own_agency=True)
    for selected in ("agency_staff", "super_admin"):
        response = await client.post("/api/v1/auth/access-level", json={"role": selected})
        assert response.status_code == 403
    me = await client.get("/api/v1/auth/me")
    assert me.json()["can_switch_access_level"] is False


@pytest.mark.asyncio
async def test_cookie_authenticated_switch_requires_csrf_but_no_mfa(db_session, client):
    _, _, _, token = await _seed(db_session, client)
    del client.headers["Authorization"]
    client.cookies.set(get_settings().jwt.access_cookie_name, token)
    response = await client.post("/api/v1/auth/access-level", json={"role": "agency_manager"})
    assert response.status_code == 403
    response = await client.post("/api/v1/auth/access-level", json={"role": "agency_manager"},
                                 headers={"Origin": get_settings().allowed_origins[0]})
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_multiple_tenants_need_explicit_scope_without_owned_groups(db_session, client):
    agency, _, _, _ = await _seed(db_session, client)
    other = AgencyModel(id=uuid.uuid4(), name="Other", email="other@example.test")
    db_session.add(other)
    await db_session.flush()
    response = await client.post("/api/v1/auth/access-level", json={"role": "agency_staff"})
    assert response.status_code == 409
    response = await client.post("/api/v1/auth/access-level",
                                 json={"role": "agency_staff", "agency_id": str(other.id)})
    assert response.status_code == 200, response.text
    assert response.json()["agency_id"] == str(other.id)
    changed = await client.post("/api/v1/auth/access-level", json={"role": "agency_manager"})
    assert changed.json()["agency_id"] == str(other.id)
    assert agency.id != other.id


@pytest.mark.asyncio
async def test_superadmin_infers_owned_group_tenant(db_session, client):
    agency, _, user, _ = await _seed(db_session, client)
    db_session.add(AgencyModel(id=uuid.uuid4(), name="Other", email="other@example.test"))
    db_session.add(ClientGroupModel(
        id=uuid.uuid4(), agency_id=agency.id, name="Owned", token=str(uuid.uuid4()),
        created_by_user_id=user.id, status="active",
    ))
    await db_session.flush()
    response = await client.post("/api/v1/auth/access-level", json={"role": "agency_staff"})
    assert response.status_code == 200, response.text
    assert response.json()["agency_id"] == str(agency.id)


@pytest.mark.asyncio
async def test_invalid_cookie_can_be_restored_using_actual_superadmin(db_session, client):
    await _seed(db_session, client)
    client.cookies.set(ACCESS_LEVEL_COOKIE, "tampered")
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    response = await client.post("/api/v1/auth/access-level", json={"role": "super_admin"})
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["sub", "sv", "expired", "deadline", "role", "type",
                                   "demoted", "inactive", "session_version"])
async def test_selected_mode_rejects_invalid_or_changed_identity(db_session, client, change):
    agency, _, user, token = await _seed(db_session, client)
    claims = decode_access_token(token)
    response = Response()
    set_access_level_cookie(response, user=user, role=UserRole.AGENCY_STAFF,
                            agency_id=agency.id, agency_name=agency.name, claims=claims)
    cookie = SimpleCookie(response.headers["set-cookie"])[ACCESS_LEVEL_COOKIE].value
    settings = get_settings()
    payload = jwt.decode(cookie, settings.app_secret_key, algorithms=[settings.jwt.algorithm])
    if change == "sub":
        payload["sub"] = str(uuid.uuid4())
    elif change == "sv":
        payload["sv"] += 1
    elif change == "expired":
        payload["exp"] = int(datetime.now(tz=UTC).timestamp()) - 5
    elif change == "deadline":
        payload["exp"] += 1000
    elif change == "role":
        payload["role"] = "super_admin"
    elif change == "type":
        payload["type"] = "access"
    elif change == "demoted":
        user.role = UserRole.AGENCY_STAFF
    elif change == "inactive":
        user.is_active = False
    else:
        user.session_version += 1
    cookie = jwt.encode(payload, settings.app_secret_key, algorithm=settings.jwt.algorithm)
    with pytest.raises(AuthenticationError):
        apply_access_level_cookie(user, {ACCESS_LEVEL_COOKIE: cookie}, claims)


@pytest.mark.asyncio
async def test_logout_clears_selected_mode(db_session, client):
    await _seed(db_session, client)
    await client.post("/api/v1/auth/access-level", json={"role": "agency_coordinator"})
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert any(ACCESS_LEVEL_COOKIE in value and "Max-Age=0" in value
               for value in response.headers.get_list("set-cookie"))


@pytest.mark.asyncio
async def test_switch_records_real_actor_in_audit(db_session, client):
    from app.infrastructure.database.models import AuditLogModel
    _, _, user, _ = await _seed(db_session, client)
    response = await client.post("/api/v1/auth/access-level", json={"role": "agency_manager"})
    assert response.status_code == 200, response.text
    audit = await db_session.scalar(select(AuditLogModel).where(
        AuditLogModel.action == "auth.access_level_changed"))
    assert audit.user_id == user.id


@pytest.mark.asyncio
async def test_refresh_keeps_selected_role_and_original_session_deadline(db_session, client):
    from app.core.security.identity_security import encrypt_mfa_secret, generate_mfa_secret
    from app.core.security.jwt import create_refresh_token
    from app.infrastructure.database.models import UserSecurityStateModel
    from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository

    _, _, user, token = await _seed(db_session, client)
    original = decode_access_token(token)
    deadline = datetime.fromtimestamp(original["session_exp"], tz=UTC)
    now = datetime.now(tz=UTC)
    db_session.add(UserSecurityStateModel(
        user_id=user.id, credential_state="active", session_version=1,
        mfa_required=True, mfa_enabled_at=now,
        mfa_secret_ciphertext=encrypt_mfa_secret(generate_mfa_secret()),
    ))
    refresh, _ = create_refresh_token(expires_at=deadline)
    await RefreshTokenRepository(db_session).save(
        token=refresh, user_id=user.id, expires_at=deadline, session_version=1,
        authentication_methods=("pwd", "totp"), mfa_authenticated_at=now,
    )
    switched = await client.post("/api/v1/auth/access-level", json={"role": "agency_staff"})
    assert switched.status_code == 200, switched.text
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert response.status_code == 200, response.text
    assert response.json()["user"]["role"] == "agency_staff"
    assert response.json()["user"]["actual_role"] == "super_admin"
    assert response.json()["user"]["can_switch_access_level"] is True
    cookies = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        cookies.load(header)
    claims = decode_access_token(cookies[get_settings().jwt.access_cookie_name].value)
    assert claims["role"] == "super_admin"
    assert claims["agency_id"] is None
    assert claims["session_exp"] == original["session_exp"]
    assert ACCESS_LEVEL_COOKIE not in cookies
    del client.headers["Authorization"]
    assert (await client.get("/api/v1/auth/me")).json()["role"] == "agency_staff"


@pytest.mark.asyncio
async def test_coordinator_mode_does_not_bypass_actual_account_sensitive_action_mfa(
    db_session, client,
):
    from fastapi import Request

    from app.core.security.access_level import apply_access_level
    from app.domain.exceptions.exceptions import StepUpRequiredError
    from app.presentation.dependencies.auth import require_recent_mfa

    agency, _, user, _ = await _seed(db_session, client)
    selected = apply_access_level(user, role=UserRole.AGENCY_COORDINATOR,
                                  agency_id=agency.id, agency_name=agency.name)
    request = Request({"type": "http", "headers": []})
    request.state.auth_claims = {"amr": ["pwd"]}
    with pytest.raises(StepUpRequiredError):
        await require_recent_mfa(request, selected)


@pytest.mark.asyncio
async def test_signed_staff_then_manager_modes_enforce_real_submission_delete(
    db_session, client, monkeypatch,
):
    from unittest.mock import AsyncMock

    from app.infrastructure.database.models import PassportSubmissionModel, StorageCleanupJobModel
    from app.presentation.api.v1.routes.passport_routes import bulk_actions

    agency, model, user, _ = await _seed(db_session, client)
    now = datetime.now(tz=UTC)
    token, _ = create_access_token(
        user.id, "super_admin", session_version=user.session_version,
        authentication_methods=("pwd", "totp"), mfa_authenticated_at=now,
        session_expires_at=now + timedelta(days=1),
    )
    client.headers["Authorization"] = "Bearer " + token
    group_id, submission_id = uuid.uuid4(), uuid.uuid4()
    db_session.add(ClientGroupModel(
        id=group_id, agency_id=agency.id, name="Owned group", token=str(uuid.uuid4()),
        created_by_user_id=user.id, status="active",
    ))
    db_session.add(PassportSubmissionModel(
        id=submission_id, agency_id=agency.id, group_id=group_id,
        client_name="Synthetic traveller", client_email="traveller@example.test",
        image_s3_key=f"{agency.id}/{group_id}/{submission_id}.jpg", status="ai_approved",
    ))
    await db_session.commit()
    propagate, cleanup = AsyncMock(), AsyncMock(return_value=None)
    monkeypatch.setattr(bulk_actions, "propagate_mobile_passenger_change", propagate)
    monkeypatch.setattr(bulk_actions, "process_storage_cleanup_job", cleanup)
    switched = await client.post("/api/v1/auth/access-level", json={"role": "agency_staff"})
    assert switched.status_code == 200, switched.text
    path = f"/api/v1/passports/groups/{group_id}/bulk-delete"
    body = {"submission_ids": [str(submission_id)]}
    denied = await client.post(path, json=body)
    assert denied.status_code == 403, denied.text
    assert await db_session.get(PassportSubmissionModel, submission_id) is not None
    propagate.assert_not_awaited()
    cleanup.assert_not_awaited()
    switched = await client.post("/api/v1/auth/access-level", json={"role": "agency_manager"})
    assert switched.status_code == 200, switched.text
    deleted = await client.post(path, json=body)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_count"] == 1
    assert await db_session.scalar(select(PassportSubmissionModel.id).where(
        PassportSubmissionModel.id == submission_id)) is None
    assert await db_session.scalar(select(StorageCleanupJobModel.id)) is not None
    propagate.assert_awaited_once()
    cleanup.assert_awaited_once()
    await db_session.refresh(model)
    assert model.role == "super_admin" and model.agency_id is None
