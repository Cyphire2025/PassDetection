from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.mobile.app_integrity import (
    AppleAppAttestRegistrationVerdict,
    MobileIntegrityRejected,
    MobileIntegrityUnavailable,
    mobile_document_authorization_request_hash,
)
from app.application.mobile.integrity_service import MobileIntegrityService
from app.core.config.settings import MobileSettings
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.security.mobile_integrity_challenges import (
    InMemoryMobileIntegrityChallengeStore,
)
from app.infrastructure.security.mobile_integrity_providers import (
    MobileIntegrityProviderRegistry,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileAppAttestRegistrationRequest,
    MobileIntegrityChallengeRequest,
    MobileIntegrityProofRequest,
)


def _claims() -> MobileAccessClaims:
    account_id = uuid.uuid4()
    return MobileAccessClaims(
        principal_id=account_id,
        account_id=account_id,
        principal_type="passenger",
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session_generation=3,
        password_change_required=False,
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
    )


def _result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _service(
    *,
    mode: str,
    session: MagicMock | None = None,
    play_verify: AsyncMock | None = None,
    apple_attestation: AsyncMock | None = None,
    apple_assertion: AsyncMock | None = None,
) -> tuple[MobileIntegrityService, MagicMock, MobileIntegrityProviderRegistry]:
    database = session or MagicMock()
    if session is None:
        database.execute = AsyncMock()
        database.flush = AsyncMock()
        database.add = MagicMock()
    providers = MobileIntegrityProviderRegistry(
        play=SimpleNamespace(verify=play_verify or AsyncMock()),  # type: ignore[arg-type]
        apple=SimpleNamespace(  # type: ignore[arg-type]
            verify_attestation=apple_attestation or AsyncMock(),
            verify_assertion=apple_assertion or AsyncMock(),
        ),
    )
    settings = SimpleNamespace(
        app_secret_key="server-secret-" * 8,
        mobile=MobileSettings(
            app_integrity_mode=mode,
            app_integrity_require_redis=mode == "enforce",
            app_attest_team_id="ABCDEFGHIJ",
        ),
    )
    return (
        MobileIntegrityService(
            session=database,
            challenge_store=InMemoryMobileIntegrityChallengeStore(),
            providers=providers,
            settings=settings,  # type: ignore[arg-type]
        ),
        database,
        providers,
    )


@pytest.mark.parametrize("mode", ["disabled", "monitor"])
@pytest.mark.asyncio
async def test_non_enforcing_modes_preserve_action_when_proof_is_missing(mode: str) -> None:
    service, session, _providers = _service(mode=mode)

    await service.enforce_action(
        claims=_claims(),
        action="document_download_authorize",
        request_hash="R" * 43,
        proof=None,
    )

    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_enforcement_rejects_missing_proof_before_database_or_provider_work() -> None:
    service, session, providers = _service(mode="enforce")

    with pytest.raises(MobileIntegrityRejected) as caught:
        await service.enforce_action(
            claims=_claims(),
            action="document_download_authorize",
            request_hash="R" * 43,
            proof=None,
        )

    assert caught.value.reason == "proof_missing"
    session.execute.assert_not_awaited()
    providers.play.verify.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_play_proof_is_one_time_and_bound_to_server_recomputed_request() -> None:
    claims = _claims()
    installation_id = "installation-identifier-0001"
    device = SimpleNamespace(
        platform="android",
        device_identifier_hash="a" * 64,
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(device))
    session.flush = AsyncMock()
    session.add = MagicMock()
    verify = AsyncMock()
    service, _session, _providers = _service(
        mode="enforce",
        session=session,
        play_verify=verify,
    )
    request_hash = mobile_document_authorization_request_hash(
        group_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        version=1,
    )
    challenge = await service.issue_challenge(
        claims=claims,
        request=MobileIntegrityChallengeRequest(
            provider="play_integrity",
            action="document_download_authorize",
            request_hash=request_hash,
            installation_id=installation_id,
        ),
    )
    assert challenge is not None
    proof = MobileIntegrityProofRequest(
        challenge_id=challenge.challenge_id,
        provider="play_integrity",
        proof="opaque-play-integrity-token",
        installation_id=installation_id,
    )

    await service.enforce_action(
        claims=claims,
        action="document_download_authorize",
        request_hash=request_hash,
        proof=proof,
    )

    verify.assert_awaited_once_with(
        integrity_token="opaque-play-integrity-token",
        expected_request_hash=challenge.provider_request_hash,
    )
    with pytest.raises(MobileIntegrityRejected) as replayed:
        await service.enforce_action(
            claims=claims,
            action="document_download_authorize",
            request_hash=request_hash,
            proof=proof,
        )
    assert replayed.value.reason == "challenge_missing_or_replayed"


@pytest.mark.parametrize("mode", ["monitor", "enforce"])
@pytest.mark.asyncio
async def test_provider_outage_respects_rollout_mode(mode: str) -> None:
    claims = _claims()
    installation_id = "installation-identifier-0002"
    device = SimpleNamespace(platform="android", device_identifier_hash="b" * 64)
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(device))
    session.flush = AsyncMock()
    session.add = MagicMock()
    verify = AsyncMock(side_effect=MobileIntegrityUnavailable("provider outage"))
    service, _session, _providers = _service(
        mode=mode,
        session=session,
        play_verify=verify,
    )
    request_hash = "R" * 43
    challenge = await service.issue_challenge(
        claims=claims,
        request=MobileIntegrityChallengeRequest(
            provider="play_integrity",
            action="document_download_authorize",
            request_hash=request_hash,
            installation_id=installation_id,
        ),
    )
    assert challenge is not None
    proof = MobileIntegrityProofRequest(
        challenge_id=challenge.challenge_id,
        provider="play_integrity",
        proof="opaque-play-integrity-token",
        installation_id=installation_id,
    )

    if mode == "enforce":
        with pytest.raises(MobileIntegrityUnavailable):
            await service.enforce_action(
                claims=claims,
                action="document_download_authorize",
                request_hash=request_hash,
                proof=proof,
            )
    else:
        await service.enforce_action(
            claims=claims,
            action="document_download_authorize",
            request_hash=request_hash,
            proof=proof,
        )


@pytest.mark.asyncio
async def test_wrong_action_hash_consumes_challenge_and_never_calls_provider() -> None:
    claims = _claims()
    installation_id = "installation-identifier-0003"
    device = SimpleNamespace(platform="android", device_identifier_hash="c" * 64)
    session = MagicMock()
    session.execute = AsyncMock(return_value=_result(device))
    session.flush = AsyncMock()
    session.add = MagicMock()
    verify = AsyncMock()
    service, _session, _providers = _service(
        mode="enforce",
        session=session,
        play_verify=verify,
    )
    challenge = await service.issue_challenge(
        claims=claims,
        request=MobileIntegrityChallengeRequest(
            provider="play_integrity",
            action="document_download_authorize",
            request_hash="R" * 43,
            installation_id=installation_id,
        ),
    )
    assert challenge is not None

    with pytest.raises(MobileIntegrityRejected) as caught:
        await service.enforce_action(
            claims=claims,
            action="document_download_authorize",
            request_hash="W" * 43,
            proof=MobileIntegrityProofRequest(
                challenge_id=challenge.challenge_id,
                provider="play_integrity",
                proof="opaque-play-integrity-token",
                installation_id=installation_id,
            ),
        )

    assert caught.value.reason == "binding_request_hash"
    verify.assert_not_awaited()


@pytest.mark.asyncio
async def test_apple_key_registration_persists_only_hash_and_verifier_material() -> None:
    claims = _claims()
    installation_id = "installation-identifier-0004"
    key_id = "K" * 48
    device = SimpleNamespace(platform="ios", device_identifier_hash="d" * 64)
    no_existing_key = _result(None)
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[_result(device), _result(device), no_existing_key]
    )
    session.flush = AsyncMock()
    session.add = MagicMock()
    verify_attestation = AsyncMock(
        return_value=AppleAppAttestRegistrationVerdict(
            verification_material=b"audited-public-material" * 2,
            counter=0,
            environment="development",
        )
    )
    service, _session, _providers = _service(
        mode="enforce",
        session=session,
        apple_attestation=verify_attestation,
    )
    from app.application.mobile.app_integrity import (
        app_attest_key_registration_request_hash,
    )

    challenge = await service.issue_challenge(
        claims=claims,
        request=MobileIntegrityChallengeRequest(
            provider="app_attest",
            action="app_attest_key_register",
            request_hash=app_attest_key_registration_request_hash(key_id=key_id),
            installation_id=installation_id,
            key_id=key_id,
        ),
    )
    assert challenge is not None

    await service.register_apple_key(
        claims=claims,
        request=MobileAppAttestRegistrationRequest(
            challenge_id=challenge.challenge_id,
            installation_id=installation_id,
            key_id=key_id,
            attestation_object="opaque-app-attest-object" * 2,
        ),
    )

    verify_attestation.assert_awaited_once_with(
        attestation_object="opaque-app-attest-object" * 2,
        key_id=key_id,
        server_challenge=challenge.provider_request_hash,
        app_id="ABCDEFGHIJ.com.globalconnects.groupcompanion",
        environment="development",
    )
    persisted = session.add.call_args.args[0]
    assert persisted.key_identifier_hash != key_id
    assert key_id not in persisted.key_identifier_hash
    assert persisted.device_identifier_hash == "d" * 64
    assert persisted.verification_material == b"audited-public-material" * 2
    session.flush.assert_awaited_once()
