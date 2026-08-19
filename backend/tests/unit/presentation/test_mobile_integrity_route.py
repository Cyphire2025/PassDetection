from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Response

from app.application.mobile.app_integrity import (
    MobileIntegrityRejected,
    MobileIntegrityUnavailable,
    create_mobile_integrity_challenge,
)
from app.core.security.mobile_jwt import MobileAccessClaims
from app.presentation.api.v1.routes.mobile_integrity import (
    issue_mobile_integrity_challenge,
    register_mobile_app_attest_key,
    router,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileAppAttestRegistrationRequest,
    MobileIntegrityChallengeRequest,
)


def _claims() -> MobileAccessClaims:
    account_id = uuid.uuid4()
    return MobileAccessClaims(
        principal_id=account_id,
        account_id=account_id,
        principal_type="passenger",
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session_generation=2,
        password_change_required=False,
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
    )


def _request() -> MobileIntegrityChallengeRequest:
    return MobileIntegrityChallengeRequest(
        provider="play_integrity",
        action="document_download_authorize",
        request_hash="R" * 43,
        installation_id="installation-identifier-0001",
    )


def test_integrity_router_exposes_only_challenge_and_key_registration() -> None:
    assert {route.path for route in router.routes} == {
        "/integrity/challenges",
        "/integrity/app-attest/keys/register",
    }


@pytest.mark.asyncio
async def test_challenge_route_is_no_store_and_reports_rollout_requirement() -> None:
    claims = _claims()
    body = _request()
    challenge = create_mobile_integrity_challenge(
        provider=body.provider,
        action=body.action,
        request_hash=body.request_hash,
        agency_id=claims.agency_id,
        account_id=claims.account_id,
        session_id=claims.session_id,
        device_identifier_hash="a" * 64,
        key_id=None,
        binding_secret=b"route-test-binding-secret",
        ttl_seconds=120,
    )
    service = SimpleNamespace(issue_challenge=AsyncMock(return_value=challenge))
    response = Response()
    with patch(
        "app.presentation.api.v1.routes.mobile_integrity.get_settings",
        return_value=SimpleNamespace(
            mobile=SimpleNamespace(app_integrity_mode="monitor")
        ),
    ):
        result = await issue_mobile_integrity_challenge(
            body=body,
            response=response,
            claims=claims,
            service=service,  # type: ignore[arg-type]
        )

    assert result.status == "issued"
    assert result.mode == "monitor"
    assert result.required is False
    assert result.challenge_id == challenge.challenge_id
    assert result.provider_request_hash == challenge.provider_request_hash
    assert response.headers["Cache-Control"] == "private, no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"


@pytest.mark.asyncio
async def test_disabled_challenge_does_not_issue_replayable_state() -> None:
    service = SimpleNamespace(issue_challenge=AsyncMock(return_value=None))
    response = Response()
    with patch(
        "app.presentation.api.v1.routes.mobile_integrity.get_settings",
        return_value=SimpleNamespace(
            mobile=SimpleNamespace(app_integrity_mode="disabled")
        ),
    ):
        result = await issue_mobile_integrity_challenge(
            body=_request(),
            response=response,
            claims=_claims(),
            service=service,  # type: ignore[arg-type]
        )

    assert result.model_dump() == {
        "status": "disabled",
        "mode": "disabled",
        "required": False,
        "provider": "play_integrity",
        "challenge_id": None,
        "provider_request_hash": None,
        "expires_at": None,
    }


@pytest.mark.parametrize(
    ("error", "status_code", "retry_after"),
    [
        (MobileIntegrityRejected("provider_token"), 403, None),
        (MobileIntegrityUnavailable("provider outage"), 503, "30"),
    ],
)
@pytest.mark.asyncio
async def test_challenge_route_maps_rejection_and_outage_without_reason_disclosure(
    error: Exception,
    status_code: int,
    retry_after: str | None,
) -> None:
    service = SimpleNamespace(issue_challenge=AsyncMock(side_effect=error))
    with patch(
        "app.presentation.api.v1.routes.mobile_integrity.get_settings",
        return_value=SimpleNamespace(mobile=SimpleNamespace(app_integrity_mode="enforce")),
    ):
        with pytest.raises(HTTPException) as caught:
            await issue_mobile_integrity_challenge(
                body=_request(),
                response=Response(),
                claims=_claims(),
                service=service,  # type: ignore[arg-type]
            )

    assert caught.value.status_code == status_code
    assert str(error) not in caught.value.detail
    assert (caught.value.headers or {}).get("Retry-After") == retry_after


@pytest.mark.asyncio
async def test_apple_registration_route_returns_only_fixed_success_state() -> None:
    service = SimpleNamespace(register_apple_key=AsyncMock(return_value=None))
    result = await register_mobile_app_attest_key(
        body=MobileAppAttestRegistrationRequest(
            challenge_id=uuid.uuid4(),
            installation_id="installation-identifier-0002",
            key_id="K" * 48,
            attestation_object="opaque-app-attest-registration-object",
        ),
        response=Response(),
        claims=_claims(),
        service=service,  # type: ignore[arg-type]
    )

    assert result.model_dump() == {"registered": True}
