from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.core.security.identity_security import identity_action_token_hash_candidates
from app.core.security.password import hash_password, verify_password
from app.infrastructure.database.models import (
    AuditLogModel,
    IdentityActionTokenModel,
    IdentityNotificationOutboxModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories import identity_security_repository
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.security import identity_notifications
from app.infrastructure.security.identity_recovery_rate_limiter import (
    IdentityRecoveryRateLimited,
)
from app.presentation.api.v1.routes import auth_identity


class _AllowRecovery:
    async def consume_network(self, **_kwargs: object) -> None:
        return None

    async def consume_account(self, **_kwargs: object) -> None:
        return None

    async def close(self) -> None:
        return None


class _BlockAccountRecovery(_AllowRecovery):
    async def consume_account(self, **_kwargs: object) -> None:
        raise IdentityRecoveryRateLimited()


async def _create_staff(
    session: AsyncSession,
    *,
    email: str,
    password: str = "ExistingPassword9!",
) -> tuple[UserModel, UserSecurityStateModel]:
    user = UserModel(
        email=email,
        hashed_password=hash_password(password),
        full_name="Recovery Test Staff",
        role="agency_staff",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    state = UserSecurityStateModel(
        user_id=user.id,
        credential_state="active",
        session_version=3,
        mfa_required=True,
    )
    session.add(state)
    await session.flush()
    return user, state


def _install_recovery_settings(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    *,
    limiter_type: type[_AllowRecovery] = _AllowRecovery,
) -> None:
    monkeypatch.setattr(auth_identity, "get_settings", lambda: settings)
    monkeypatch.setattr(auth_identity, "IdentityRecoveryRateLimiter", limiter_type)


@pytest.mark.asyncio
async def test_known_and_unknown_recovery_requests_have_same_neutral_contract(
    client: AsyncClient,
    db_session: AsyncSession,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = await _create_staff(db_session, email="known-recovery@example.com")
    settings = test_settings.model_copy(
        update={
            "password_recovery_delivery_provider": "development",
            "password_recovery_development_expose_token": False,
        }
    )
    _install_recovery_settings(monkeypatch, settings)

    known = await client.post(
        "/api/v1/auth/password/recovery/request",
        json={"email": user.email},
        headers={"User-Agent": "identity-contract-test"},
    )
    unknown = await client.post(
        "/api/v1/auth/password/recovery/request",
        json={"email": "unknown-recovery@example.com"},
        headers={"User-Agent": "identity-contract-test"},
    )

    assert known.status_code == unknown.status_code == 202
    assert (
        known.json()
        == unknown.json()
        == {
            "message": "If the account can be recovered, reset instructions are available.",
            "development_recovery_token": None,
        }
    )
    assert known.headers["cache-control"] == unknown.headers["cache-control"]
    assert known.headers["cache-control"] == "private, no-store, max-age=0"
    token = (
        await db_session.execute(
            select(IdentityActionTokenModel).where(IdentityActionTokenModel.user_id == user.id)
        )
    ).scalar_one()
    outbox = (
        await db_session.execute(
            select(IdentityNotificationOutboxModel).where(
                IdentityNotificationOutboxModel.action_token_id == token.id
            )
        )
    ).scalar_one()
    assert token.token_hash != ""
    assert outbox.status == "pending"
    assert (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == "auth.password_recovery_requested")
        )
    ).scalar_one().metadata_json["delivery_staged"] is True


@pytest.mark.asyncio
async def test_production_recovery_never_exposes_raw_token_even_if_flag_is_forced(
    client: AsyncClient,
    db_session: AsyncSession,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = await _create_staff(db_session, email="production-recovery@example.com")
    # model_copy deliberately bypasses Settings validation to prove the route
    # itself cannot leak a token even under an impossible/unsafe flag state.
    settings = test_settings.model_copy(
        update={
            "app_env": "production",
            "password_recovery_delivery_provider": "smtp",
            "password_recovery_smtp_host": "smtp.example.test",
            "password_recovery_smtp_sender": "security@example.test",
            "password_recovery_development_expose_token": True,
        }
    )
    _install_recovery_settings(monkeypatch, settings)

    response = await client.post(
        "/api/v1/auth/password/recovery/request",
        json={"email": user.email},
    )

    assert response.status_code == 202
    assert response.json()["development_recovery_token"] is None
    token = (
        await db_session.execute(
            select(IdentityActionTokenModel).where(IdentityActionTokenModel.user_id == user.id)
        )
    ).scalar_one()
    assert token.token_hash not in response.text


@pytest.mark.asyncio
async def test_replacement_invalidates_old_token_and_terminalizes_old_delivery(
    client: AsyncClient,
    db_session: AsyncSession,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = await _create_staff(db_session, email="replacement-recovery@example.com")
    settings = test_settings.model_copy(
        update={
            "password_recovery_delivery_provider": "development",
            "password_recovery_development_expose_token": True,
        }
    )
    _install_recovery_settings(monkeypatch, settings)

    # Timestamp ties and random UUID order do not identify issuance order.
    # Force the newer token/outbox to sort first so that association assertions
    # cannot accidentally depend on timestamp or primary-key ordering again.
    issued_at = datetime.now(tz=UTC).replace(microsecond=0)

    class TiedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return issued_at.astimezone(tz) if tz else issued_at.replace(tzinfo=None)

    for module, identifiers in (
        (identity_security_repository, (
            uuid.UUID("ffffffff-ffff-4fff-8fff-fffffffffff2"),
            uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"),
        )),
        (identity_notifications, (
            uuid.UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee4"),
            uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3"),
        )),
    ):
        monkeypatch.setattr(module, "datetime", TiedDateTime)
        monkeypatch.setattr(module, "uuid", SimpleNamespace(UUID=uuid.UUID, uuid4=iter(identifiers).__next__))

    first_response = await client.post(
        "/api/v1/auth/password/recovery/request",
        json={"email": user.email},
    )
    assert first_response.status_code == 202
    first_raw = first_response.json()["development_recovery_token"]
    second_response = await client.post(
        "/api/v1/auth/password/recovery/request",
        json={"email": user.email},
    )
    assert second_response.status_code == 202
    second_raw = second_response.json()["development_recovery_token"]

    assert isinstance(first_raw, str) and isinstance(second_raw, str)
    assert first_raw != second_raw
    tokens = (
        (
            await db_session.execute(
                select(IdentityActionTokenModel)
                .where(IdentityActionTokenModel.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(tokens) == 2
    tokens_by_hash = {(row.token_key_id, row.token_hash): row for row in tokens}

    def issued_token(raw: str) -> IdentityActionTokenModel:
        matches = [tokens_by_hash[key] for key in identity_action_token_hash_candidates(
            raw, purpose="password_recovery",
        ) if key in tokens_by_hash]
        assert len(matches) == 1
        return matches[0]

    first_token, second_token = issued_token(first_raw), issued_token(second_raw)
    assert first_token.created_at == second_token.created_at
    assert first_token.id > second_token.id
    assert first_token.invalidated_at is not None
    assert second_token.invalidated_at is None
    outboxes = (
        (
            await db_session.execute(
                select(IdentityNotificationOutboxModel)
                .where(IdentityNotificationOutboxModel.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(outboxes) == 2
    outboxes_by_token = {row.action_token_id: row for row in outboxes}
    assert set(outboxes_by_token) == {first_token.id, second_token.id}
    first_outbox = outboxes_by_token[first_token.id]
    second_outbox = outboxes_by_token[second_token.id]
    assert first_outbox.created_at == second_outbox.created_at
    assert first_outbox.id > second_outbox.id
    assert (first_outbox.status, first_outbox.last_error_code) == ("dead_letter", "superseded")
    assert (second_outbox.status, second_outbox.last_error_code) == ("pending", None)
    repository = IdentitySecurityRepository(db_session)
    assert await repository.get_valid_action_token(raw_token=first_raw, purpose="password_recovery") is None
    assert await repository.get_valid_action_token(raw_token=second_raw, purpose="password_recovery") is second_token
    rejected = await client.post(
        "/api/v1/auth/password/recovery/complete",
        json={"token": first_raw, "new_password": "ReplacementPassword9!"},
    )
    assert rejected.status_code == 401


@pytest.mark.asyncio
async def test_password_recovery_consumes_once_revokes_sessions_and_audits(
    client: AsyncClient,
    db_session: AsyncSession,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, state = await _create_staff(db_session, email="complete-recovery@example.com")
    from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
    refresh = await RefreshTokenRepository(db_session).save(
        token="existing-refresh-credential", user_id=user.id,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1), session_version=state.session_version,
    )
    settings = test_settings.model_copy(
        update={
            "password_recovery_delivery_provider": "development",
            "password_recovery_development_expose_token": True,
        }
    )
    _install_recovery_settings(monkeypatch, settings)
    requested = await client.post(
        "/api/v1/auth/password/recovery/request",
        json={"email": user.email},
    )
    raw_token = requested.json()["development_recovery_token"]
    assert isinstance(raw_token, str)

    completed = await client.post(
        "/api/v1/auth/password/recovery/complete",
        json={"token": raw_token, "new_password": "RecoveredPassword9!"},
    )
    replay = await client.post(
        "/api/v1/auth/password/recovery/complete",
        json={"token": raw_token, "new_password": "AnotherRecoveredPassword9!"},
    )

    assert completed.status_code == 200
    assert completed.json()["status"] == "mfa_enrollment_required"
    assert replay.status_code == 401
    await db_session.refresh(user)
    await db_session.refresh(state)
    await db_session.refresh(refresh)
    assert verify_password("RecoveredPassword9!", user.hashed_password)
    assert state.session_version == 4
    assert refresh.is_revoked is True
    token = (
        await db_session.execute(
            select(IdentityActionTokenModel).where(IdentityActionTokenModel.user_id == user.id)
        )
    ).scalar_one()
    assert token.consumed_at is not None
    recovered_audit = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == "auth.password_recovered")
        )
    ).scalar_one()
    assert recovered_audit.metadata_json["sessions_revoked"] is True


@pytest.mark.asyncio
async def test_expired_recovery_token_is_rejected_without_password_change(
    client: AsyncClient,
    db_session: AsyncSession,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = await _create_staff(db_session, email="expired-recovery@example.com")
    original_hash = user.hashed_password
    repository = IdentitySecurityRepository(db_session)
    _, raw_token = await repository.issue_action_token(
        user_id=user.id,
        purpose="password_recovery",
        expires_in=timedelta(minutes=20),
        now=datetime.now(tz=UTC) - timedelta(hours=1),
    )
    _install_recovery_settings(monkeypatch, test_settings)

    response = await client.post(
        "/api/v1/auth/password/recovery/complete",
        json={"token": raw_token, "new_password": "ExpiredAttemptPassword9!"},
    )

    assert response.status_code == 401
    await db_session.refresh(user)
    assert user.hashed_password == original_hash


@pytest.mark.asyncio
async def test_account_rate_limit_preserves_existing_recovery_link_and_neutral_response(
    client: AsyncClient,
    db_session: AsyncSession,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, _ = await _create_staff(db_session, email="limited-recovery@example.com")
    repository = IdentitySecurityRepository(db_session)
    existing, _ = await repository.issue_action_token(
        user_id=user.id,
        purpose="password_recovery",
        expires_in=timedelta(minutes=20),
    )
    _install_recovery_settings(
        monkeypatch,
        test_settings,
        limiter_type=_BlockAccountRecovery,
    )

    response = await client.post(
        "/api/v1/auth/password/recovery/request",
        json={"email": user.email},
    )

    assert response.status_code == 202
    assert response.json()["development_recovery_token"] is None
    await db_session.refresh(existing)
    assert existing.invalidated_at is None
    assert (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == "auth.password_recovery_suppressed")
        )
    ).scalar_one().result == "blocked"
