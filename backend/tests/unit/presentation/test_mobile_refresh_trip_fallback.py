"""Real refresh requests preserve an account's other already authorized trips."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security.mobile_jwt import (
    create_mobile_access_token,
    decode_mobile_access_token,
    hash_mobile_lookup,
    hash_mobile_refresh_token,
)
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobilePassengerIdentityModel,
    MobilePassengerSessionIdentityModel,
    MobileRefreshTokenModel,
)
from tests.authored_notification_fixtures import authored_audience
from tests.unit.presentation.test_gc_app_group_removal import remove

pytestmark = pytest.mark.asyncio
REFRESH = "/api/v1/mobile/auth/refresh"
RAW_TOKEN = "synthetic-refresh-token-trip-fallback-123456"
INSTALLATION = "synthetic-installation-trip-fallback"


async def context(session, monkeypatch):
    monkeypatch.setattr("app.presentation.api.v1.routes.mobile_auth._require_mobile_enabled", lambda: None)
    actor, accesses, submissions, claims, _ = await authored_audience(session)
    device = await session.get(MobileDeviceSessionModel, claims.session_id)
    token = await session.scalar(select(MobileRefreshTokenModel))
    identity = await session.get(MobilePassengerIdentityModel, device.passenger_identity_id)
    identity.status = "claimed"
    identity.claimed_at = datetime.now(UTC)
    device.device_identifier_hash = hash_mobile_lookup(INSTALLATION, purpose="device-installation")
    device.session_generation = 1
    device.expires_at = datetime.now(UTC) + timedelta(days=7)
    token.expires_at = device.expires_at
    token.token_hash = hash_mobile_refresh_token(RAW_TOKEN)
    await session.commit()
    return actor, accesses, submissions, device, token


async def refresh(client):
    return await client.post(REFRESH, json={"refresh_token": RAW_TOKEN, "installation_id": INSTALLATION})


async def test_refresh_of_removed_selected_trip_uses_existing_binding_and_invalidates_old_bearer(client, db_session, monkeypatch):
    actor, accesses, _, device, token = await context(db_session, monkeypatch)
    account_id, session_id = device.account_id, device.id
    previous_access_token, _ = create_mobile_access_token(
        principal_id=device.passenger_identity_id, account_id=account_id, principal_type="passenger",
        agency_id=device.agency_id, session_id=session_id, session_generation=1,
    )
    before_bindings = set(await db_session.scalars(select(MobilePassengerSessionIdentityModel.passenger_identity_id)))
    await remove(db_session, actor, accesses[0].group_id, accesses[0].revision)

    response = await refresh(client)
    assert response.status_code == 200, response.text
    body = response.json()
    await db_session.commit()
    assert body["principal"]["account_id"] == str(account_id)
    assert body["session_id"] == str(session_id)
    assert device.selected_group_id == accesses[1].group_id
    assert device.selected_gc_group_access_id == accesses[1].id
    assert body["principal"]["id"] == str(device.passenger_identity_id)
    assert device.session_generation == 2 and device.last_sync_acknowledged_at is None
    assert token.consumed_at is not None
    assert set(await db_session.scalars(select(MobilePassengerSessionIdentityModel.passenger_identity_id))) == before_bindings
    current = decode_mobile_access_token(body["access_token"])
    assert current.account_id == account_id and current.session_generation == 2
    assert (await client.get("/api/v1/mobile/me", headers={"authorization": f"Bearer {body['access_token']}"})).status_code == 200
    assert (await client.get("/api/v1/mobile/me", headers={"authorization": f"Bearer {previous_access_token}"})).status_code == 401
    assert (await client.get(f"/api/v1/mobile/trips/{accesses[0].group_id}/manifest", headers={"authorization": f"Bearer {body['access_token']}"})).status_code == 403
    assert (await client.get(f"/api/v1/mobile/trips/{accesses[1].group_id}/manifest", headers={"authorization": f"Bearer {body['access_token']}"})).status_code == 200


async def test_refresh_keeps_current_authorized_selection(client, db_session, monkeypatch):
    _, accesses, _, device, _ = await context(db_session, monkeypatch)
    principal_id = device.passenger_identity_id
    response = await refresh(client)
    assert response.status_code == 200, response.text
    assert device.passenger_identity_id == principal_id
    assert device.selected_group_id == accesses[0].group_id and device.session_generation == 1


@pytest.mark.parametrize("unavailable", ["removed", "paused", "future", "ended", "unbound", "role_disabled"])
async def test_refresh_never_selects_an_unavailable_or_unproven_trip(client, db_session, monkeypatch, unavailable):
    actor, accesses, _, device, token = await context(db_session, monkeypatch)
    selected_id = device.passenger_identity_id
    await remove(db_session, actor, accesses[0].group_id, accesses[0].revision)
    alternative = accesses[1]
    if unavailable == "removed":
        await remove(db_session, actor, alternative.group_id, alternative.revision)
    elif unavailable == "paused":
        alternative.is_enabled = False
    elif unavailable == "future":
        alternative.access_starts_at = datetime.now(UTC) + timedelta(days=1)
    elif unavailable == "ended":
        alternative.access_expires_at = datetime.now(UTC) - timedelta(days=1)
    elif unavailable == "role_disabled":
        alternative.passenger_access_enabled = False
    else:
        binding = await db_session.scalar(select(MobilePassengerSessionIdentityModel).where(
            MobilePassengerSessionIdentityModel.gc_group_access_id == alternative.id,
        ))
        await db_session.delete(binding)
    await db_session.commit()
    response = await refresh(client)
    assert response.status_code == 401
    assert device.passenger_identity_id == selected_id and device.session_generation == 1
    assert token.consumed_at is None


@pytest.mark.parametrize("invalid", ["token_revoked", "session_revoked", "changed_contact", "claim_generation"])
async def test_fallback_does_not_bypass_session_or_identity_revocation(client, db_session, monkeypatch, invalid):
    actor, accesses, submissions, device, token = await context(db_session, monkeypatch)
    await remove(db_session, actor, accesses[0].group_id, accesses[0].revision)
    if invalid == "token_revoked":
        token.revoked_at = datetime.now(UTC)
    elif invalid == "session_revoked":
        device.status = "revoked"
        device.revoked_at = datetime.now(UTC)
        device.revoke_reason = "synthetic_revocation"
    elif invalid == "changed_contact":
        submissions[1].client_phone = "+919000000099"
    else:
        identity = await db_session.scalar(select(MobilePassengerIdentityModel).where(
            MobilePassengerIdentityModel.passenger_submission_id == submissions[1].id,
        ))
        identity.claim_generation += 1
    await db_session.commit()
    assert (await refresh(client)).status_code == 401
    assert device.selected_group_id == accesses[0].group_id and token.consumed_at is None
