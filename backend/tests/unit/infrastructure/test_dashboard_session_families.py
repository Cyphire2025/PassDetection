"""Copied credentials and replay are fenced by actual persisted session state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.application.dashboard_realtime_authorization import load_dashboard_realtime_authorization
from app.application.use_cases.auth.logout_all_use_case import LogoutAllUseCase
from app.core.security.jwt import create_access_token, decode_access_token
from app.domain.exceptions.exceptions import AuthenticationError
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    DashboardSessionModel,
    NotificationModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository


async def create_session(session, *, user=None):
    if user is None:
        agency = AgencyModel(id=uuid.uuid4(), name="Session fixture", email=f"agency-{uuid.uuid4().hex}@example.test")
        session.add(agency)
        await session.flush()
        user = UserModel(id=uuid.uuid4(), email=f"session-{uuid.uuid4()}@example.test",
                         full_name="Synthetic session", hashed_password="unused", role="agency_staff",
                         agency_id=agency.id, is_active=True)
        session.add(user)
        await session.flush()
        session.add(UserSecurityStateModel(user_id=user.id, credential_state="active", session_version=1))
        await session.flush()
    raw = str(uuid.uuid4())
    now = datetime.now(UTC)
    row = await RefreshTokenRepository(session).save(
        raw, user.id, now + timedelta(days=1), authentication_methods=("pwd", "totp"),
        mfa_authenticated_at=now,
    )
    access = create_access_token(user.id, user.role, user.agency_id,
                                 session_id=row.session_id, session_expires_at=now + timedelta(days=1))[0]
    return user, raw, access, row.session_id


@pytest.mark.asyncio
@pytest.mark.parametrize("logout_credential", ["refresh", "access"])
async def test_logout_rejects_copied_cookie_and_bearer_but_keeps_other_session(client, db_session, logout_credential):
    user, refresh, access, family_id = await create_session(db_session)
    _, other_refresh, other_access, _ = await create_session(db_session, user=user)
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})).status_code == 200
    if logout_credential == "refresh":
        response = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    else:
        response = await client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert response.status_code == 204
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})).status_code == 401
    client.cookies.set("access_token", access)
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    client.cookies.clear()
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {other_access}"})).status_code == 200
    assert await RefreshTokenRepository(db_session).get_valid_token(other_refresh) is not None
    assert (await db_session.get(DashboardSessionModel, family_id)).revoked_at is not None
    with pytest.raises(AuthenticationError):
        await load_dashboard_realtime_authorization(db_session, access, maximum_trips=100)


@pytest.mark.asyncio
async def test_stolen_first_then_replayed_refresh_revokes_successor_and_audits(client, db_session):
    user, original, access, family_id = await create_session(db_session)
    _, independent, independent_access, _ = await create_session(db_session, user=user)
    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert rotated.status_code == 200
    successor = rotated.cookies["refresh_token"]
    successor_access = rotated.cookies["access_token"]
    assert decode_access_token(successor_access)["sid"] == str(family_id)
    client.cookies.clear()
    # An unknown random credential must not revoke any family.
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": str(uuid.uuid4())})).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {successor_access}"})).status_code == 200
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"
    assert (await client.post("/api/v1/auth/refresh", json={"refresh_token": successor})).status_code == 401
    for stolen in (access, successor_access):
        assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {stolen}"})).status_code == 401
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {independent_access}"})).status_code == 200
    assert await RefreshTokenRepository(db_session).get_valid_token(independent) is not None
    assert (await db_session.scalars(select(AuditLogModel).where(AuditLogModel.action == "auth.refresh_reuse_detected"))).one()
    notification = (await db_session.scalars(select(NotificationModel))).one()
    assert notification.user_id == user.id and notification.agency_id == user.agency_id


@pytest.mark.asyncio
async def test_logout_all_and_legacy_cutover_fence_dashboard_access(client, db_session):
    user, _, access, _ = await create_session(db_session)
    _, _, second, _ = await create_session(db_session, user=user)
    legacy = create_access_token(user.id, user.role, user.agency_id)[0]
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {legacy}"})).status_code == 401
    await LogoutAllUseCase(RefreshTokenRepository(db_session), IdentitySecurityRepository(db_session)).execute(user.id)
    for token in (access, second):
        assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401


@pytest.mark.asyncio
async def test_session_claim_cannot_be_rebound_to_other_user(client, db_session):
    _, _, _, family = await create_session(db_session)
    other, _, _, _ = await create_session(db_session)
    wrong = create_access_token(other.id, other.role, other.agency_id, session_id=family)[0]
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {wrong}"})).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,credential", [
    ("logout", "body"), ("logout", "cookie"), ("logout", "access"),
    ("refresh", "body"), ("refresh", "cookie"),
])
async def test_expected_actor_mismatch_keeps_newer_session_and_cookies(
    client, db_session, test_settings, endpoint, credential,
):
    user, refresh, access, family_id = await create_session(db_session)
    headers = {"X-Expected-Actor-Id": str(uuid.uuid4())}
    body = None
    if credential == "cookie":
        client.cookies.set(test_settings.jwt.refresh_cookie_name, refresh, path="/api/v1/auth")
        headers["Origin"] = test_settings.allowed_origins[0]
    elif credential == "access":
        headers["Authorization"] = f"Bearer {access}"
    else:
        body = {"refresh_token": refresh}
    response = await client.post(f"/api/v1/auth/{endpoint}", json=body, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AUTH_REQUEST_OWNER_CHANGED"
    assert response.headers.get_list("set-cookie") == []
    assert await RefreshTokenRepository(db_session).get_valid_token(refresh) is not None
    assert (await db_session.get(DashboardSessionModel, family_id)).revoked_at is None
    client.cookies.clear()
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["logout", "refresh"])
async def test_matching_actor_precondition_preserves_normal_session_command(client, db_session, endpoint):
    user, refresh, access, family_id = await create_session(db_session)
    response = await client.post(f"/api/v1/auth/{endpoint}", json={"refresh_token": refresh},
                                 headers={"X-Expected-Actor-Id": str(user.id)})
    assert response.status_code == (204 if endpoint == "logout" else 200)
    assert response.headers.get_list("set-cookie")
    family = await db_session.get(DashboardSessionModel, family_id)
    assert (family.revoked_at is not None) == (endpoint == "logout")


@pytest.mark.asyncio
async def test_stale_actor_cannot_revoke_newer_family_through_consumed_refresh_replay(client, db_session):
    user, original, access, family_id = await create_session(db_session)
    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": original})
    assert rotated.status_code == 200
    successor = rotated.cookies["refresh_token"]
    client.cookies.clear()
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": original},
                                 headers={"X-Expected-Actor-Id": str(uuid.uuid4())})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AUTH_REQUEST_OWNER_CHANGED"
    assert response.headers.get_list("set-cookie") == []
    assert await RefreshTokenRepository(db_session).get_valid_token(successor) is not None
    assert (await db_session.get(DashboardSessionModel, family_id)).revoked_at is None
    assert not (await db_session.scalars(select(AuditLogModel).where(
        AuditLogModel.action == "auth.refresh_reuse_detected",
    ))).all()


@pytest.mark.asyncio
async def test_mixed_logout_credentials_are_checked_before_either_family_is_revoked(client, db_session):
    first, first_refresh, _, first_family = await create_session(db_session)
    second, second_refresh, second_access, second_family = await create_session(db_session)
    response = await client.post("/api/v1/auth/logout", json={"refresh_token": first_refresh}, headers={
        "Authorization": f"Bearer {second_access}", "X-Expected-Actor-Id": str(first.id),
    })
    assert response.status_code == 409
    assert response.headers.get_list("set-cookie") == []
    for refresh, family_id in [(first_refresh, first_family), (second_refresh, second_family)]:
        assert await RefreshTokenRepository(db_session).get_valid_token(refresh) is not None
        assert (await db_session.get(DashboardSessionModel, family_id)).revoked_at is None
