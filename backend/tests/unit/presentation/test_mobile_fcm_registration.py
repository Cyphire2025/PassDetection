"""Real SQLite/HTTP registration regressions using synthetic devices and tokens."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.security.mobile_jwt import (
    MobileAccessClaims,
    create_mobile_access_token,
    hash_mobile_lookup,
)
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobilePushRegistrationModel,
)
from app.infrastructure.database.models import AgencyModel, UserModel
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes import mobile_ops
from app.presentation.middleware.error_handler import register_exception_handlers


@pytest.fixture(autouse=True)
def synthetic_settings(monkeypatch, test_settings):
    for module in (
        "app.core.security.mobile_jwt",
        "app.core.security.mobile_push_crypto",
        "app.presentation.api.v1.routes.mobile_ops",
    ):
        monkeypatch.setattr(f"{module}.get_settings", lambda: test_settings)


async def _device(db_session, *, agency_id=None, platform="android"):
    now = datetime.now(tz=UTC)
    if agency_id is None:
        agency_id = uuid.uuid4()
        db_session.add(
            AgencyModel(
                id=agency_id,
                name="Synthetic FCM test agency",
                email=f"{agency_id.hex}@example.invalid",
            )
        )
    user_id = uuid.uuid4()
    user = UserModel(
        id=user_id,
        agency_id=agency_id,
        email=f"{user_id.hex}@example.invalid",
        full_name="Synthetic coordinator",
        hashed_password="unused-test-password-hash",
        role="agency_coordinator",
        is_active=True,
    )
    installation = f"synthetic-installation-{uuid.uuid4().hex}"
    device = MobileDeviceSessionModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        subject_role="coordinator",
        user_id=user_id,
        account_id=user_id,
        passenger_identity_id=None,
        passenger_subject_hash=None,
        device_identifier_hash=hash_mobile_lookup(installation, purpose="device-installation"),
        platform=platform,
        app_version="1.0.4",
        status="active",
        session_generation=3,
        refresh_family_id=uuid.uuid4(),
        created_at=now - timedelta(hours=1),
        last_seen_at=now,
        expires_at=now + timedelta(days=1),
    )
    db_session.add_all([user, device])
    await db_session.flush()
    claims = MobileAccessClaims(
        principal_id=user_id,
        account_id=user_id,
        principal_type="coordinator",
        agency_id=agency_id,
        session_id=device.id,
        session_generation=3,
        password_change_required=False,
        expires_at=now + timedelta(minutes=10),
    )
    return device, claims, installation, user


def _registration(device, provider, *, state="active", token=None):
    token = token or f"synthetic-{provider}-token-{uuid.uuid4().hex}"
    return MobilePushRegistrationModel(
        id=uuid.uuid4(),
        agency_id=device.agency_id,
        session_id=device.id,
        provider=provider,
        platform=device.platform,
        environment="development",
        app_bundle_id="com.globalconnects.groupcompanion",
        token_ciphertext=mobile_push_fernet().encrypt(token.encode()),
        token_lookup_hash=hash_mobile_lookup(token, purpose="push-token"),
        token_key_version=1,
        status=state,
        notifications_authorized=state == "active",
        revoked_at=datetime.now(tz=UTC) if state == "revoked" else None,
    )


def _snapshot(registration):
    values = {}
    for column in MobilePushRegistrationModel.__table__.columns:
        value = getattr(registration, column.name)
        # SQLite drops timezone metadata on reload, while timestamps retain UTC.
        values[column.name] = value.replace(tzinfo=UTC) if isinstance(value, datetime) else value
    return values


async def _request(db_session, claims, installation, *, token=None, provider="fcm", headers=None):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(mobile_ops.router)

    async def database():
        yield db_session

    app.dependency_overrides[get_db_session] = database
    if headers is None:
        bearer, _ = create_mobile_access_token(
            principal_id=claims.principal_id,
            account_id=claims.account_id,
            principal_type=claims.principal_type,
            agency_id=claims.agency_id,
            session_id=claims.session_id,
            session_generation=claims.session_generation,
        )
        headers = {"Authorization": f"Bearer {bearer}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/push/register",
            headers=headers,
            json={
                "provider": provider,
                "installation_id": installation,
                "push_token": token or f"synthetic-native-token-{uuid.uuid4().hex}",
            },
        )


@pytest.mark.asyncio
async def test_fcm_revokes_same_session_expo_and_fcm_only_and_encrypts_token(db_session, caplog):
    device, claims, installation, _ = await _device(db_session)
    other_device, _, _, _ = await _device(db_session, agency_id=claims.agency_id)
    other_agency, _, _, _ = await _device(db_session)
    replaced = [_registration(device, "expo"), _registration(device, "fcm")]
    preserved = [
        _registration(device, "expo", state="disabled"),
        _registration(device, "fcm", state="revoked"),
        _registration(other_device, "expo"),
        _registration(other_device, "fcm"),
        _registration(other_agency, "expo"),
        _registration(other_agency, "fcm"),
    ]
    db_session.add_all(replaced + preserved)
    await db_session.flush()
    preserved_before = {row.id: _snapshot(row) for row in preserved}
    replaced_before = {row.id: _snapshot(row) for row in replaced}
    token = "synthetic-native-fcm-token-never-return-to-client"
    response = await _request(db_session, claims, installation, token=token)
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"registration_id", "registered"}
    assert payload["registered"] is True
    assert token not in response.text and token not in caplog.text
    assert installation not in response.text
    await db_session.commit()
    db_session.expire_all()
    rows = list(
        (
            await db_session.execute(
                select(MobilePushRegistrationModel).options(
                    undefer(MobilePushRegistrationModel.token_ciphertext)
                )
            )
        ).scalars()
    )
    by_id = {row.id: row for row in rows}
    assert len(rows) == 9  # All eight prior rows are retained.
    for identifier, before in preserved_before.items():
        assert _snapshot(by_id[identifier]) == before
    for identifier, before in replaced_before.items():
        row = by_id[identifier]
        assert row.status == "revoked" and row.notifications_authorized is False
        assert row.revoked_at is not None
        assert row.token_ciphertext == before["token_ciphertext"]
        assert row.token_lookup_hash == before["token_lookup_hash"]
    registered = by_id[uuid.UUID(payload["registration_id"])]
    assert registered.provider == "fcm" and registered.status == "active"
    assert registered.session_id == claims.session_id and registered.agency_id == claims.agency_id
    assert registered.notifications_authorized is True and registered.revoked_at is None
    assert registered.token_ciphertext != token.encode()
    assert mobile_push_fernet().decrypt(registered.token_ciphertext).decode() == token
    assert registered.token_lookup_hash == hash_mobile_lookup(token, purpose="push-token")
    assert "token" not in payload and "phone" not in payload


@pytest.mark.asyncio
async def test_same_token_registration_reactivates_existing_row_without_duplicates(db_session):
    device, claims, installation, _ = await _device(db_session)
    token = "synthetic-fcm-token-for-registration-retry"
    existing = _registration(device, "fcm", state="revoked", token=token)
    existing.last_failure_at = datetime.now(tz=UTC)
    existing.last_failure_code = "DeviceNotRegistered"
    previous_expo = _registration(device, "expo")
    db_session.add_all([existing, previous_expo])
    await db_session.flush()
    for _ in range(2):
        response = await _request(db_session, claims, installation, token=token)
        assert response.status_code == 200
        assert response.json()["registration_id"] == str(existing.id)
    assert len(list((await db_session.execute(select(MobilePushRegistrationModel))).scalars())) == 2
    assert existing.status == "active" and existing.revoked_at is None
    assert existing.last_failure_at is None and existing.last_failure_code is None
    assert previous_expo.status == "revoked"


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_agency", [False, True])
async def test_token_bound_to_another_installation_cannot_be_taken_over(db_session, foreign_agency):
    device, claims, installation, _ = await _device(db_session)
    other, _, _, _ = await _device(
        db_session,
        agency_id=None if foreign_agency else claims.agency_id,
    )
    token = "synthetic-fcm-token-held-by-another-installation"
    previous_expo = _registration(device, "expo")
    existing = _registration(other, "fcm", token=token)
    db_session.add_all([previous_expo, existing])
    await db_session.flush()
    before = [_snapshot(previous_expo), _snapshot(existing)]
    response = await _request(db_session, claims, installation, token=token)
    assert response.status_code == 403
    assert [_snapshot(previous_expo), _snapshot(existing)] == before
    assert token not in response.text and installation not in response.text


@pytest.mark.asyncio
async def test_installation_mismatch_cannot_register_or_revoke_previous_expo(db_session):
    device, claims, _, _ = await _device(db_session)
    previous = _registration(device, "expo")
    db_session.add(previous)
    await db_session.flush()
    response = await _request(db_session, claims, "different-synthetic-installation")
    assert response.status_code == 403
    assert previous.status == "active" and previous.revoked_at is None
    assert len(list((await db_session.execute(select(MobilePushRegistrationModel))).scalars())) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("platform,provider", [("ios", "fcm"), ("android", "apns")])
async def test_native_provider_must_match_authenticated_device_platform(
    db_session, platform, provider
):
    device, claims, installation, _ = await _device(db_session, platform=platform)
    previous = _registration(device, "expo")
    db_session.add(previous)
    await db_session.flush()
    response = await _request(db_session, claims, installation, provider=provider)
    assert response.status_code == 403
    assert previous.status == "active"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["expired", "revoked", "agency", "generation", "inactive_user"])
async def test_authentication_failures_preserve_existing_registrations(db_session, failure):
    device, claims, installation, user = await _device(db_session)
    previous = _registration(device, "expo")
    db_session.add(previous)
    if failure == "expired":
        device.expires_at = datetime.now(tz=UTC) - timedelta(minutes=1)
    elif failure == "revoked":
        device.status = "revoked"
        device.revoked_at = datetime.now(tz=UTC)
    elif failure == "agency":
        claims = replace(claims, agency_id=uuid.uuid4())
    elif failure == "generation":
        claims = replace(claims, session_generation=claims.session_generation + 1)
    else:
        user.is_active = False
    await db_session.flush()
    response = await _request(db_session, claims, installation)
    assert response.status_code == 401
    assert previous.status == "active" and previous.revoked_at is None
    assert len(list((await db_session.execute(select(MobilePushRegistrationModel))).scalars())) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid-synthetic-token"}])
async def test_missing_or_invalid_bearer_cannot_register(db_session: AsyncSession, headers):
    _, claims, installation, _ = await _device(db_session)
    response = await _request(db_session, claims, installation, headers=headers)
    assert response.status_code == 401
    assert not list((await db_session.execute(select(MobilePushRegistrationModel))).scalars())
