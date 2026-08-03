from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.application.mobile.otp_provider import OTPDeliveryError
from app.core.security.mobile_jwt import MobileAccessClaims, hash_mobile_otp_code
from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import AuthenticationError
from app.presentation.api.v1.routes.mobile_auth import (
    _complete_neutral_otp_timing,
    _eligible_passenger_identities,
    _issue_session,
    _verify_challenge_code,
    mobile_credential_login,
    refresh_mobile_session,
    request_passenger_otp,
    switch_passenger_trip,
    verify_passenger_claim,
    verify_passenger_otp,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileClaimVerifyRequest,
    MobileCredentialLoginRequest,
    MobileDeviceInput,
    MobileOTPRequest,
    MobileOTPVerifyRequest,
    MobilePassengerTripSwitchRequest,
    MobilePrincipalResponse,
    MobileRefreshRequest,
    MobileTokenResponse,
)
from app.presentation.dependencies.mobile_auth import get_current_mobile_claims


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"user-agent", b"mobile-auth-test")],
            "client": ("127.0.0.1", 12345),
        }
    )


def _device() -> MobileDeviceInput:
    return MobileDeviceInput(
        installation_id="installation-mobile-auth-test",
        platform="android",
        app_version="1.0.0",
    )


def _tokens(*, principal_type: str = "passenger") -> MobileTokenResponse:
    now = datetime.now(tz=UTC)
    principal_id = uuid.uuid4()
    return MobileTokenResponse(
        access_token="access-token",
        refresh_token="refresh-token-that-is-long-enough-for-the-contract",
        access_token_expires_at=now + timedelta(minutes=15),
        refresh_token_expires_at=now + timedelta(days=30),
        session_id=uuid.uuid4(),
        principal=MobilePrincipalResponse(
            id=principal_id,
            account_id=principal_id,
            principal_type=principal_type,
            agency_id=uuid.uuid4(),
            display_name="Mobile Test User",
        ),
    )


def _challenge(*, code: str = "123456", **overrides: object) -> SimpleNamespace:
    challenge_id = uuid.uuid4()
    values: dict[str, object] = {
        "id": challenge_id,
        "status": "pending",
        "expires_at": datetime.now(tz=UTC) + timedelta(minutes=5),
        "resend_available_at": datetime.now(tz=UTC) + timedelta(seconds=60),
        "code_hash": hash_mobile_otp_code(challenge_id, code),
        "attempt_count": 0,
        "max_attempts": 3,
        "phone_lookup_hash": "phone-lookup-hash",
        "verified_at": None,
        "updated_at": datetime.now(tz=UTC),
        "consumed_at": None,
        "passenger_identity_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _otp_settings() -> SimpleNamespace:
    return SimpleNamespace(
        enabled=True,
        otp_development_code=None,
        otp_provider="whatsapp",
        otp_ttl_seconds=300,
        otp_max_attempts=5,
        otp_resend_cooldown_seconds=60,
    )


@pytest.mark.asyncio
async def test_request_otp_reuses_pending_challenge_during_resend_cooldown() -> None:
    challenge = _challenge()
    result = MagicMock()
    result.scalar_one_or_none.return_value = challenge
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    limiter = MagicMock()
    limiter.consume = AsyncMock()
    mobile_settings = SimpleNamespace(enabled=True)

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth.get_settings",
            return_value=SimpleNamespace(mobile=mobile_settings),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.MobileOTPRateLimiter",
            return_value=limiter,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.get_otp_provider"
        ) as provider_factory,
        patch(
            "app.presentation.api.v1.routes.mobile_auth._complete_neutral_otp_timing",
            AsyncMock(),
        ) as neutral_timing,
    ):
        response = await request_passenger_otp(
            MobileOTPRequest(phone_number="+91 98732 99928"),
            _request("/api/v1/mobile/auth/otp/request"),
            session,
        )

    assert response.challenge_id == challenge.id
    assert 1 <= response.resend_after_seconds <= 60
    limiter.consume.assert_awaited_once()
    provider_factory.assert_not_called()
    session.commit.assert_awaited_once()
    neutral_timing.assert_awaited_once()


@pytest.mark.asyncio
async def test_otp_challenge_is_committed_before_provider_delivery() -> None:
    events: list[str] = []
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=no_existing)
    session.flush = AsyncMock()
    session.rollback = AsyncMock()

    async def commit() -> None:
        events.append("commit")

    session.commit = AsyncMock(side_effect=commit)
    identity = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    provider = MagicMock()

    async def send_code(**_: object) -> str:
        events.append("provider")
        return "wamid.otp-test"

    provider.send_code = AsyncMock(side_effect=send_code)
    audit = MagicMock()
    audit.record = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth.get_settings",
            return_value=SimpleNamespace(mobile=_otp_settings()),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.MobileOTPRateLimiter.consume",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._reconcile_phone_candidate_groups",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._eligible_passenger_identities",
            AsyncMock(
                return_value=[
                    (identity, SimpleNamespace(), SimpleNamespace())
                ]
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.get_otp_provider",
            return_value=provider,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._complete_neutral_otp_timing",
            AsyncMock(),
        ),
    ):
        response = await request_passenger_otp(
            MobileOTPRequest(phone_number="+91 98732 99928"),
            _request("/api/v1/mobile/auth/otp/request"),
            session,
        )

    assert response.challenge_id == session.add.call_args.args[0].id
    assert events == ["commit", "provider", "commit"]
    assert session.flush.await_count == 1
    challenge = session.add.call_args.args[0]
    assert challenge.provider_reference == "wamid.otp-test"
    assert challenge.status == "pending"
    provider.send_code.assert_awaited_once()


@pytest.mark.asyncio
async def test_ineligible_otp_request_is_neutral_and_never_calls_provider() -> None:
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=no_existing)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    provider_factory = MagicMock()
    audit = MagicMock()
    audit.record = AsyncMock()
    neutral_timing = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth.get_settings",
            return_value=SimpleNamespace(mobile=_otp_settings()),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.MobileOTPRateLimiter.consume",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._reconcile_phone_candidate_groups",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._eligible_passenger_identities",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.get_otp_provider",
            provider_factory,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._complete_neutral_otp_timing",
            neutral_timing,
        ),
    ):
        response = await request_passenger_otp(
            MobileOTPRequest(phone_number="+91 98732 99928"),
            _request("/api/v1/mobile/auth/otp/request"),
            session,
        )

    assert response.expires_in_seconds == 300
    assert response.resend_after_seconds == 60
    provider_factory.assert_not_called()
    assert session.commit.await_count == 2
    neutral_timing.assert_awaited_once()
    metadata = audit.record.await_args.kwargs["metadata"]
    assert metadata["delivery_status"] == "not_attempted"
    assert metadata["eligible_identity_count"] == 0


@pytest.mark.asyncio
async def test_concurrent_otp_request_returns_database_winner_without_second_send() -> None:
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None
    winner = _challenge()
    winner_result = MagicMock()
    winner_result.scalar_one_or_none.return_value = winner
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[no_existing, winner_result])
    session.flush = AsyncMock(
        side_effect=IntegrityError("insert", {}, RuntimeError("duplicate pending"))
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    provider_factory = MagicMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth.get_settings",
            return_value=SimpleNamespace(mobile=_otp_settings()),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.MobileOTPRateLimiter.consume",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._reconcile_phone_candidate_groups",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._eligible_passenger_identities",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.get_otp_provider",
            provider_factory,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._complete_neutral_otp_timing",
            AsyncMock(),
        ),
    ):
        response = await request_passenger_otp(
            MobileOTPRequest(phone_number="+91 98732 99928"),
            _request("/api/v1/mobile/auth/otp/request"),
            session,
        )

    assert response.challenge_id == winner.id
    session.rollback.assert_awaited_once()
    session.commit.assert_awaited_once()
    provider_factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("delivery_unknown", "expected_challenge_status", "expected_audit_status"),
    [
        (False, "cancelled", "failed"),
        (True, "pending", "unknown"),
    ],
)
async def test_provider_delivery_failures_keep_neutral_response_and_safe_state(
    delivery_unknown: bool,
    expected_challenge_status: str,
    expected_audit_status: str,
) -> None:
    no_existing = MagicMock()
    no_existing.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=no_existing)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    identity = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    provider = MagicMock()
    provider.send_code = AsyncMock(
        side_effect=OTPDeliveryError(
            "safe failure",
            code="SAFE_PROVIDER_CODE",
            delivery_unknown=delivery_unknown,
        )
    )
    audit = MagicMock()
    audit.record = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth.get_settings",
            return_value=SimpleNamespace(mobile=_otp_settings()),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.MobileOTPRateLimiter.consume",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._reconcile_phone_candidate_groups",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._eligible_passenger_identities",
            AsyncMock(
                return_value=[
                    (identity, SimpleNamespace(), SimpleNamespace())
                ]
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.get_otp_provider",
            return_value=provider,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._complete_neutral_otp_timing",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.logger.warning"
        ) as safe_log,
    ):
        response = await request_passenger_otp(
            MobileOTPRequest(phone_number="+91 98732 99928"),
            _request("/api/v1/mobile/auth/otp/request"),
            session,
        )

    assert response.expires_in_seconds == 300
    challenge = session.add.call_args.args[0]
    assert challenge.status == expected_challenge_status
    assert challenge.provider_reference is None
    if delivery_unknown:
        assert challenge.resend_available_at == challenge.expires_at
    metadata = audit.record.await_args.kwargs["metadata"]
    assert metadata["delivery_status"] == expected_audit_status
    assert metadata["provider_error_code"] == "SAFE_PROVIDER_CODE"
    logged = repr(safe_log.call_args)
    assert "+919873299928" not in logged
    assert "123456" not in logged


@pytest.mark.asyncio
async def test_neutral_otp_timing_uses_bounded_floor_and_jitter() -> None:
    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth.time.monotonic",
            return_value=10.2,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.asyncio.sleep",
            AsyncMock(),
        ) as sleep,
    ):
        await _complete_neutral_otp_timing(10.0, jitter_ms=100)

    sleep.assert_awaited_once_with(pytest.approx(0.55))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "expected_status", "expected_attempts"),
    [
        ({}, "pending", 1),
        ({"attempt_count": 2}, "locked", 3),
        (
            {"expires_at": datetime.now(tz=UTC) - timedelta(seconds=1)},
            "expired",
            0,
        ),
    ],
    ids=("wrong-code", "max-attempts", "expired-code"),
)
async def test_verify_otp_rejects_wrong_expired_and_exhausted_codes(
    overrides: dict[str, object],
    expected_status: str,
    expected_attempts: int,
) -> None:
    challenge = _challenge(**overrides)
    session = MagicMock()
    session.commit = AsyncMock()

    with pytest.raises(HTTPException) as caught:
        await _verify_challenge_code(session, challenge, "999999")

    assert caught.value.status_code == 401
    assert caught.value.detail == "Invalid or expired verification code"
    assert challenge.status == expected_status
    assert challenge.attempt_count == expected_attempts
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_otp_issues_passenger_session_for_one_active_identity() -> None:
    challenge = _challenge()
    identity = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        phone_lookup_hash=challenge.phone_lookup_hash,
        is_shared_number=False,
        requires_secondary_verification=False,
    )
    access = SimpleNamespace(id=uuid.uuid4())
    tokens = _tokens()
    session = MagicMock()
    session.commit = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth._require_mobile_enabled"
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._locked_challenge",
            AsyncMock(return_value=challenge),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._verify_challenge_code",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._eligible_passenger_identities",
            AsyncMock(return_value=[(identity, access, SimpleNamespace())]),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._issue_passenger_session",
            AsyncMock(return_value=tokens),
        ) as issue_session,
        patch(
            "app.presentation.api.v1.routes.mobile_auth._audit_mobile_auth",
            AsyncMock(),
        ),
    ):
        response = await verify_passenger_otp(
            MobileOTPVerifyRequest(
                challenge_id=challenge.id,
                code="123456",
                device=_device(),
            ),
            _request("/api/v1/mobile/auth/otp/verify"),
            session,
        )

    assert response.status == "authenticated"
    assert response.tokens == tokens
    assert challenge.status == "consumed"
    assert challenge.passenger_identity_id == identity.id
    issue_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_otp_requires_secondary_proof_for_cross_group_phone() -> None:
    challenge = _challenge()
    agency_id = uuid.uuid4()
    identities = [
        SimpleNamespace(
            id=uuid.uuid4(),
            agency_id=agency_id,
            phone_lookup_hash=challenge.phone_lookup_hash,
            is_shared_number=False,
            requires_secondary_verification=False,
        )
        for _ in range(2)
    ]
    eligible = [
        (identity, SimpleNamespace(id=uuid.uuid4()), SimpleNamespace())
        for identity in identities
    ]
    tokens = _tokens()
    session = MagicMock()

    with (
        patch("app.presentation.api.v1.routes.mobile_auth._require_mobile_enabled"),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._locked_challenge",
            AsyncMock(return_value=challenge),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._verify_challenge_code",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._eligible_passenger_identities",
            AsyncMock(return_value=eligible),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._issue_passenger_session",
            AsyncMock(return_value=tokens),
        ) as issue_session,
        patch(
            "app.presentation.api.v1.routes.mobile_auth._audit_mobile_auth",
            AsyncMock(),
        ),
    ):
        response = await verify_passenger_otp(
            MobileOTPVerifyRequest(
                challenge_id=challenge.id,
                code="123456",
                device=_device(),
            ),
            _request("/api/v1/mobile/auth/otp/verify"),
            session,
        )

    assert response.status == "secondary_verification_required"
    assert response.claims == []
    assert challenge.passenger_identity_id is None
    issue_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_verify_otp_does_not_merge_unshared_rows_across_tenants() -> None:
    challenge = _challenge()
    eligible = [
        (
            SimpleNamespace(
                id=uuid.uuid4(),
                agency_id=uuid.uuid4(),
                phone_lookup_hash=challenge.phone_lookup_hash,
                is_shared_number=False,
                requires_secondary_verification=False,
            ),
            SimpleNamespace(id=uuid.uuid4()),
            SimpleNamespace(),
        )
        for _ in range(2)
    ]
    session = MagicMock()

    with (
        patch("app.presentation.api.v1.routes.mobile_auth._require_mobile_enabled"),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._locked_challenge",
            AsyncMock(return_value=challenge),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._verify_challenge_code",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._eligible_passenger_identities",
            AsyncMock(return_value=eligible),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._issue_passenger_session",
            AsyncMock(),
        ) as issue_session,
    ):
        response = await verify_passenger_otp(
            MobileOTPVerifyRequest(
                challenge_id=challenge.id,
                code="123456",
                device=_device(),
            ),
            _request("/api/v1/mobile/auth/otp/verify"),
            session,
        )

    assert response.status == "secondary_verification_required"
    assert response.claims == []
    issue_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_verify_otp_denies_challenge_when_no_identity_remains_eligible() -> None:
    challenge = _challenge()
    session = MagicMock()
    session.commit = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth._require_mobile_enabled"
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._locked_challenge",
            AsyncMock(return_value=challenge),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._verify_challenge_code",
            AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._eligible_passenger_identities",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._issue_passenger_session",
            AsyncMock(),
        ) as issue_session,
    ):
        with pytest.raises(HTTPException) as caught:
            await verify_passenger_otp(
                MobileOTPVerifyRequest(
                    challenge_id=challenge.id,
                    code="123456",
                    device=_device(),
                ),
                _request("/api/v1/mobile/auth/otp/verify"),
                session,
            )

    assert caught.value.status_code == 401
    assert caught.value.detail == "Invalid or expired verification code"
    session.commit.assert_awaited_once()
    issue_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_issuance_revokes_same_device_before_creating_new_family() -> None:
    session = MagicMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock()
    agency_id = uuid.uuid4()
    access = SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4())
    identity = SimpleNamespace(
        id=uuid.uuid4(),
        passenger_submission_id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        phone_lookup_hash="f" * 64,
        status="claimed",
        revoked_at=None,
        claim_generation=2,
    )
    now = datetime.now(tz=UTC)

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth._revoke_same_device_session",
            AsyncMock(),
        ) as revoke_same_device,
        patch(
            "app.presentation.api.v1.routes.mobile_auth.hash_mobile_lookup",
            side_effect=lambda value, purpose: f"{purpose}:{value}",
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.create_mobile_refresh_token",
            return_value=("r" * 48, now + timedelta(days=30)),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.hash_mobile_refresh_token",
            return_value="refresh-hash",
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.create_mobile_access_token",
            return_value=("access-token", now + timedelta(minutes=15)),
        ),
    ):
        response = await _issue_session(
            session,
            principal_id=identity.id,
            principal_type="passenger",
            agency_id=agency_id,
            display_name="Passenger",
            device=_device(),
            request=_request("/api/v1/mobile/auth/otp/verify"),
            password_change_required=False,
            passenger_identity=identity,
            access=access,
        )

    assert response.principal.passenger_id == identity.passenger_submission_id

    revoke_same_device.assert_awaited_once()
    assert response.access_token == "access-token"
    assert response.refresh_token == "r" * 48
    persisted = session.add_all.call_args.args[0]
    assert len(persisted) == 3
    assert persisted[2].passenger_identity_id == identity.id
    assert persisted[2].identity_claim_generation == 2
    assert persisted[0].account_id == identity.id
    assert response.principal.account_id == identity.id
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_credential_login_rejects_inactive_account_without_issuing_session() -> None:
    user = SimpleNamespace(
        id=uuid.uuid4(),
        email="coordinator@example.com",
        role=UserRole.AGENCY_COORDINATOR.value,
        is_active=False,
        agency_id=uuid.uuid4(),
        hashed_password="hashed",
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = user
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    limiter = MagicMock()
    limiter.check_allowed = AsyncMock()
    limiter.record_failure = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth._require_mobile_enabled"
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.LoginAttemptLimiter",
            return_value=limiter,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._issue_user_session",
            AsyncMock(),
        ) as issue_session,
    ):
        with pytest.raises(HTTPException) as caught:
            await mobile_credential_login(
                MobileCredentialLoginRequest(
                    email="coordinator@example.com",
                    password="StrongPassword!2026",
                    device=_device(),
                ),
                _request("/api/v1/mobile/auth/login"),
                session,
            )

    assert caught.value.status_code == 401
    assert caught.value.detail == "Invalid email or password"
    limiter.record_failure.assert_awaited_once()
    issue_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_credential_login_rejects_invitation_account_until_token_activation() -> None:
    agency_id = uuid.uuid4()
    user = SimpleNamespace(
        id=uuid.uuid4(),
        email="invited@example.com",
        role=UserRole.CLIENT_MANAGER.value,
        is_active=True,
        agency_id=agency_id,
        hashed_password="hashed",
    )
    profile = SimpleNamespace(
        status="invited",
        invitation_token_hash="a" * 64,
        invitation_expires_at=datetime.now(tz=UTC) + timedelta(days=1),
        force_password_change=True,
    )
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = profile
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[user_result, profile_result])
    limiter = MagicMock()
    limiter.check_allowed = AsyncMock()
    limiter.record_failure = AsyncMock()
    limiter.record_success = AsyncMock()

    with (
        patch("app.presentation.api.v1.routes.mobile_auth._require_mobile_enabled"),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.LoginAttemptLimiter",
            return_value=limiter,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.verify_password",
            return_value=True,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._issue_user_session",
            AsyncMock(),
        ) as issue_session,
    ):
        with pytest.raises(HTTPException) as caught:
            await mobile_credential_login(
                MobileCredentialLoginRequest(
                    email="invited@example.com",
                    password="StrongPassword!2026",
                    device=_device(),
                ),
                _request("/api/v1/mobile/auth/login"),
                session,
            )

    assert caught.value.status_code == 401
    assert caught.value.detail == "Invalid email or password"
    limiter.record_failure.assert_awaited_once()
    limiter.record_success.assert_not_awaited()
    issue_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_credential_login_allows_restricted_temporary_password_flow() -> None:
    agency_id = uuid.uuid4()
    user = SimpleNamespace(
        id=uuid.uuid4(),
        email="temporary@example.com",
        role=UserRole.CLIENT_MANAGER.value,
        is_active=True,
        agency_id=agency_id,
        hashed_password="hashed",
        last_login_at=None,
        updated_at=None,
    )
    profile = SimpleNamespace(
        status="invited",
        invitation_token_hash=None,
        invitation_expires_at=None,
        force_password_change=True,
    )
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    profile_result = MagicMock()
    profile_result.scalar_one_or_none.return_value = profile
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[user_result, profile_result])
    limiter = MagicMock()
    limiter.check_allowed = AsyncMock()
    limiter.record_failure = AsyncMock()
    limiter.record_success = AsyncMock()
    tokens = _tokens(principal_type="client_manager")

    with (
        patch("app.presentation.api.v1.routes.mobile_auth._require_mobile_enabled"),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.LoginAttemptLimiter",
            return_value=limiter,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.verify_password",
            return_value=True,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._issue_user_session",
            AsyncMock(return_value=tokens),
        ) as issue_session,
        patch(
            "app.presentation.api.v1.routes.mobile_auth._audit_mobile_auth",
            AsyncMock(),
        ),
    ):
        response = await mobile_credential_login(
            MobileCredentialLoginRequest(
                email="temporary@example.com",
                password="StrongPassword!2026",
                device=_device(),
            ),
            _request("/api/v1/mobile/auth/login"),
            session,
        )

    assert response == tokens
    limiter.record_failure.assert_not_awaited()
    limiter.record_success.assert_awaited_once()
    assert issue_session.await_args.kwargs["password_change_required"] is True


@pytest.mark.asyncio
async def test_live_client_manager_session_rejects_unredeemed_invitation_profile() -> None:
    agency_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    account_id = uuid.uuid4()
    claims = SimpleNamespace(
        session_id=uuid.uuid4(),
        agency_id=agency_id,
        principal_type="client_manager",
        principal_id=principal_id,
        account_id=account_id,
        session_generation=4,
        password_change_required=True,
    )
    device_session = SimpleNamespace(
        account_id=account_id,
        user_id=principal_id,
        last_seen_at=datetime.now(tz=UTC),
    )
    user = SimpleNamespace(id=principal_id)
    profile = SimpleNamespace(
        status="invited",
        invitation_token_hash="b" * 64,
        invitation_expires_at=datetime.now(tz=UTC) + timedelta(days=1),
        force_password_change=True,
    )
    results = []
    for value in (device_session, user, profile):
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        results.append(result)
    session = MagicMock()
    session.execute = AsyncMock(side_effect=results)

    with patch(
        "app.presentation.dependencies.mobile_auth.decode_mobile_access_token",
        return_value=claims,
    ):
        with pytest.raises(AuthenticationError, match="profile is inactive"):
            await get_current_mobile_claims(
                HTTPAuthorizationCredentials(scheme="Bearer", credentials="mobile-token"),
                session,
            )


@pytest.mark.asyncio
async def test_eligible_identity_query_excludes_suspended_or_revoked_access() -> None:
    result = MagicMock()
    result.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    assert await _eligible_passenger_identities(session, "phone-lookup-hash") == []

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "mobile_passenger_identities.status IN ('eligible', 'claimed')" in sql
    assert "mobile_passenger_identities.revoked_at IS NULL" in sql
    assert "gc_group_access.is_enabled IS true" in sql
    assert "gc_group_access.passenger_access_enabled IS true" in sql
    assert "gc_group_access.revoked_at IS NULL" in sql


@pytest.mark.asyncio
async def test_revoked_or_suspended_device_session_is_rejected_before_principal_lookup() -> None:
    claims = SimpleNamespace(
        session_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        principal_type="passenger",
        principal_id=uuid.uuid4(),
        session_generation=4,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    with patch(
        "app.presentation.dependencies.mobile_auth.decode_mobile_access_token",
        return_value=claims,
    ):
        with pytest.raises(AuthenticationError, match="no longer active"):
            await get_current_mobile_claims(
                HTTPAuthorizationCredentials(scheme="Bearer", credentials="mobile-token"),
                session,
            )

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "mobile_device_sessions.status = 'active'" in sql
    assert "mobile_device_sessions.revoked_at IS NULL" in sql
    assert "mobile_device_sessions.session_generation = 4" in sql


@pytest.mark.asyncio
async def test_current_passenger_requires_exact_live_session_identity_membership() -> None:
    claims = SimpleNamespace(
        session_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        principal_type="passenger",
        principal_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        session_generation=4,
    )
    device_session = SimpleNamespace(
        account_id=claims.account_id,
        passenger_identity_id=claims.principal_id,
        selected_gc_group_access_id=uuid.uuid4(),
        selected_group_id=uuid.uuid4(),
    )
    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = device_session
    identity_result = MagicMock()
    identity_result.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[session_result, identity_result])

    with patch(
        "app.presentation.dependencies.mobile_auth.decode_mobile_access_token",
        return_value=claims,
    ):
        with pytest.raises(AuthenticationError, match="identity is inactive"):
            await get_current_mobile_claims(
                HTTPAuthorizationCredentials(scheme="Bearer", credentials="mobile-token"),
                session,
            )

    statement = session.execute.await_args_list[1].args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "mobile_passenger_session_identities.session_id" in sql
    assert claims.session_id.hex in sql
    assert claims.agency_id.hex in sql
    assert claims.principal_id.hex in sql
    assert "mobile_passenger_identities.claim_generation = " in sql
    assert "mobile_passenger_session_identities.identity_claim_generation" in sql


@pytest.mark.asyncio
async def test_current_mobile_claims_rejects_account_namespace_swapping() -> None:
    claims = _passenger_claims(
        principal_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
    )
    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = SimpleNamespace(
        account_id=uuid.uuid4(),
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=session_result)

    with patch(
        "app.presentation.dependencies.mobile_auth.decode_mobile_access_token",
        return_value=claims,
    ):
        with pytest.raises(AuthenticationError, match="account mismatch"):
            await get_current_mobile_claims(
                HTTPAuthorizationCredentials(
                    scheme="Bearer", credentials="mobile-token"
                ),
                session,
            )

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_selected_claim_authorizes_every_identity_proven_by_the_same_factor() -> None:
    challenge = _challenge(
        status="verified",
        verified_at=datetime.now(tz=UTC),
    )
    agency_id = uuid.uuid4()
    first = SimpleNamespace(id=uuid.uuid4(), agency_id=agency_id)
    second = SimpleNamespace(id=uuid.uuid4(), agency_id=agency_id)
    other_tenant = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    first_row = (first, SimpleNamespace(id=uuid.uuid4()), SimpleNamespace())
    second_row = (second, SimpleNamespace(id=uuid.uuid4()), SimpleNamespace())
    other_tenant_row = (
        other_tenant,
        SimpleNamespace(id=uuid.uuid4()),
        SimpleNamespace(),
    )
    tokens = _tokens()
    session = MagicMock()

    with (
        patch("app.presentation.api.v1.routes.mobile_auth._require_mobile_enabled"),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._locked_challenge",
            AsyncMock(return_value=challenge),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._eligible_passenger_identities",
            AsyncMock(return_value=[first_row, second_row, other_tenant_row]),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._matching_passenger_claims",
            return_value=[first_row, second_row, other_tenant_row],
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._issue_passenger_session",
            AsyncMock(return_value=tokens),
        ) as issue_session,
        patch(
            "app.presentation.api.v1.routes.mobile_auth._audit_mobile_auth",
            AsyncMock(),
        ),
    ):
        response = await verify_passenger_claim(
            MobileClaimVerifyRequest(
                challenge_id=challenge.id,
                claim_id=second.id,
                verification_value="EMP-101",
                device=_device(),
            ),
            _request("/api/v1/mobile/auth/claim/verify"),
            session,
        )

    assert response.status == "authenticated"
    assert challenge.passenger_identity_id == second.id
    assert issue_session.await_args.kwargs["identity"] is second
    assert issue_session.await_args.kwargs["authorized_identities"] == [first, second]


def _passenger_claims(
    *,
    principal_id: uuid.UUID,
    agency_id: uuid.UUID,
    session_id: uuid.UUID,
    generation: int = 3,
    account_id: uuid.UUID | None = None,
) -> MobileAccessClaims:
    return MobileAccessClaims(
        principal_id=principal_id,
        account_id=account_id or principal_id,
        principal_type="passenger",
        agency_id=agency_id,
        session_id=session_id,
        session_generation=generation,
        password_change_required=False,
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
    )


@pytest.mark.asyncio
async def test_passenger_trip_switch_rotates_subject_and_both_token_types() -> None:
    agency_id = uuid.uuid4()
    session_id = uuid.uuid4()
    old_identity_id = uuid.uuid4()
    target_group_id = uuid.uuid4()
    target_identity = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=target_group_id,
        gc_group_access_id=uuid.uuid4(),
        passenger_submission_id=uuid.uuid4(),
        status="claimed",
        claimed_at=datetime.now(tz=UTC),
        last_verified_at=None,
        updated_at=None,
    )
    access = SimpleNamespace(
        id=target_identity.gc_group_access_id,
        agency_id=agency_id,
        group_id=target_group_id,
    )
    device_session = SimpleNamespace(
        id=session_id,
        agency_id=agency_id,
        account_id=old_identity_id,
        subject_role="passenger",
        passenger_identity_id=old_identity_id,
        selected_gc_group_access_id=uuid.uuid4(),
        selected_group_id=uuid.uuid4(),
        status="active",
        session_generation=3,
        refresh_family_id=uuid.uuid4(),
        last_seen_at=None,
        last_sync_acknowledged_at=datetime.now(tz=UTC),
        last_ip_hash=None,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
        updated_at=None,
    )
    device_result = MagicMock()
    device_result.scalar_one_or_none.return_value = device_session
    target_result = MagicMock()
    target_result.all.return_value = [
        (SimpleNamespace(), target_identity, access, SimpleNamespace())
    ]
    generation_result = MagicMock()
    generation_result.scalar_one.return_value = 7
    update_result = MagicMock()
    display_result = MagicMock()
    display_result.scalar_one.return_value = "Selected Passenger"
    refresh_lock_result = MagicMock()
    refresh_lock_result.scalars.return_value.all.return_value = [uuid.uuid4()]
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            refresh_lock_result,
            device_result,
            target_result,
            generation_result,
            update_result,
            display_result,
        ]
    )
    session.add = MagicMock()
    session.flush = AsyncMock()
    claims = _passenger_claims(
        principal_id=old_identity_id,
        agency_id=agency_id,
        session_id=session_id,
    )
    now = datetime.now(tz=UTC)

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_auth.create_mobile_refresh_token",
            return_value=("r" * 48, now + timedelta(days=30)),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.hash_mobile_refresh_token",
            return_value="h" * 64,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.create_mobile_access_token",
            return_value=("new-access", now + timedelta(minutes=15)),
        ) as create_access,
        patch(
            "app.presentation.api.v1.routes.mobile_auth._request_digest",
            return_value="i" * 64,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._audit_mobile_auth",
            AsyncMock(),
        ),
    ):
        response = await switch_passenger_trip(
            MobilePassengerTripSwitchRequest(group_id=target_group_id),
            _request("/api/v1/mobile/auth/passenger/trip/switch"),
            claims,
            session,
        )

    assert response.principal.id == target_identity.id
    assert response.principal.account_id == old_identity_id
    assert response.access_token == "new-access"
    assert device_session.passenger_identity_id == target_identity.id
    assert device_session.selected_group_id == target_group_id
    assert device_session.last_sync_acknowledged_at is None
    assert device_session.session_generation == 4
    replacement = session.add.call_args.args[0]
    assert replacement.token_generation == 8
    create_access.assert_called_once_with(
        principal_id=target_identity.id,
        account_id=old_identity_id,
        principal_type="passenger",
        agency_id=agency_id,
        session_id=session_id,
        session_generation=4,
        password_change_required=False,
    )


@pytest.mark.asyncio
async def test_passenger_trip_switch_cannot_resurrect_revoked_refresh_family() -> None:
    agency_id = uuid.uuid4()
    session_id = uuid.uuid4()
    refresh_lock_result = MagicMock()
    refresh_lock_result.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=refresh_lock_result)

    with pytest.raises(HTTPException) as caught:
        await switch_passenger_trip(
            MobilePassengerTripSwitchRequest(group_id=uuid.uuid4()),
            _request("/api/v1/mobile/auth/passenger/trip/switch"),
            _passenger_claims(
                principal_id=uuid.uuid4(),
                agency_id=agency_id,
                session_id=session_id,
            ),
            session,
        )

    assert caught.value.status_code == 401
    assert caught.value.detail == "Mobile session is no longer active"
    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "mobile_refresh_tokens.expires_at" in sql
    assert "mobile_refresh_tokens.revoked_at IS NULL" in sql


@pytest.mark.asyncio
async def test_passenger_trip_switch_denies_identifier_swapping_and_other_tenants() -> None:
    agency_id = uuid.uuid4()
    session_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    requested_group_id = uuid.uuid4()
    device_session = SimpleNamespace(
        id=session_id,
        agency_id=agency_id,
        account_id=identity_id,
        passenger_identity_id=identity_id,
        session_generation=3,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    device_result = MagicMock()
    device_result.scalar_one_or_none.return_value = device_session
    target_result = MagicMock()
    target_result.all.return_value = []
    refresh_lock_result = MagicMock()
    refresh_lock_result.scalars.return_value.all.return_value = [uuid.uuid4()]
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[refresh_lock_result, device_result, target_result]
    )
    claims = _passenger_claims(
        principal_id=identity_id,
        agency_id=agency_id,
        session_id=session_id,
    )

    with pytest.raises(HTTPException) as caught:
        await switch_passenger_trip(
            MobilePassengerTripSwitchRequest(group_id=requested_group_id),
            _request("/api/v1/mobile/auth/passenger/trip/switch"),
            claims,
            session,
        )

    assert caught.value.status_code == 403
    assert caught.value.detail == "Passenger trip is not authorized"
    target_statement = session.execute.await_args_list[2].args[0]
    sql = str(target_statement.compile(compile_kwargs={"literal_binds": True}))
    assert session_id.hex in sql
    assert agency_id.hex in sql
    assert requested_group_id.hex in sql
    assert "mobile_passenger_session_identities.session_id" in sql
    assert "mobile_passenger_session_identities.agency_id" in sql


@pytest.mark.asyncio
async def test_passenger_trip_switch_query_denies_revoked_disabled_expired_or_stale_rows() -> None:
    agency_id = uuid.uuid4()
    session_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    device_result = MagicMock()
    device_result.scalar_one_or_none.return_value = SimpleNamespace(
        id=session_id,
        agency_id=agency_id,
        passenger_identity_id=identity_id,
        session_generation=3,
        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
    )
    target_result = MagicMock()
    target_result.all.return_value = []
    refresh_lock_result = MagicMock()
    refresh_lock_result.scalars.return_value.all.return_value = [uuid.uuid4()]
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[refresh_lock_result, device_result, target_result]
    )
    claims = _passenger_claims(
        principal_id=identity_id,
        agency_id=agency_id,
        session_id=session_id,
    )

    with pytest.raises(HTTPException):
        await switch_passenger_trip(
            MobilePassengerTripSwitchRequest(group_id=uuid.uuid4()),
            _request("/api/v1/mobile/auth/passenger/trip/switch"),
            claims,
            session,
        )

    statement = session.execute.await_args_list[2].args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "mobile_passenger_identities.revoked_at IS NULL" in sql
    assert "gc_group_access.is_enabled IS true" in sql
    assert "gc_group_access.passenger_access_enabled IS true" in sql
    assert "gc_group_access.revoked_at IS NULL" in sql
    assert "gc_group_access.access_starts_at" in sql
    assert "gc_group_access.access_expires_at" in sql
    assert "client_groups.status IN ('active', 'closed')" in sql
    assert "client_groups.deleted_at IS NULL" in sql
    assert "mobile_passenger_identities.claim_generation = " in sql
    assert "mobile_passenger_session_identities.identity_claim_generation" in sql


@pytest.mark.asyncio
async def test_refresh_rotation_locks_token_before_its_device_session() -> None:
    now = datetime.now(tz=UTC)
    agency_id = uuid.uuid4()
    session_id = uuid.uuid4()
    family_id = uuid.uuid4()
    stored = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=session_id,
        agency_id=agency_id,
        family_id=family_id,
        consumed_at=None,
        revoked_at=None,
        expires_at=now + timedelta(days=1),
        token_generation=4,
        reuse_detected_at=None,
    )
    account_id = uuid.uuid4()
    device_session = SimpleNamespace(
        id=session_id,
        agency_id=agency_id,
        account_id=account_id,
        refresh_family_id=family_id,
        subject_role="passenger",
        status="active",
        revoked_at=None,
        expires_at=now + timedelta(days=1),
        session_generation=3,
        last_refresh_at=None,
        last_seen_at=None,
        last_ip_hash=None,
        updated_at=None,
    )
    stored_result = MagicMock()
    stored_result.scalar_one_or_none.return_value = stored
    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = device_session
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[stored_result, session_result])
    session.add = MagicMock()
    principal = SimpleNamespace(id=uuid.uuid4())

    with (
        patch("app.presentation.api.v1.routes.mobile_auth._require_mobile_enabled"),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._refresh_principal",
            AsyncMock(return_value=(principal, "Passenger", False)),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.create_mobile_refresh_token",
            return_value=("n" * 48, now + timedelta(days=30)),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.hash_mobile_refresh_token",
            side_effect=["lookup-hash", "replacement-hash"],
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth.create_mobile_access_token",
            return_value=("access", now + timedelta(minutes=15)),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_auth._request_digest",
            return_value="i" * 64,
        ),
    ):
        response = await refresh_mobile_session(
            MobileRefreshRequest(refresh_token="r" * 48),
            _request("/api/v1/mobile/auth/refresh"),
            session,
        )

    assert response.access_token == "access"
    assert response.principal.account_id == account_id
    assert stored.consumed_at is not None
    replacement = session.add.call_args.args[0]
    assert replacement.parent_token_id == stored.id
    assert replacement.token_generation == 5
    token_sql = str(
        session.execute.await_args_list[0].args[0].compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    device_sql = str(
        session.execute.await_args_list[1].args[0].compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "FROM mobile_refresh_tokens" in token_sql
    assert "mobile_device_sessions" not in token_sql
    assert "FROM mobile_device_sessions" in device_sql
