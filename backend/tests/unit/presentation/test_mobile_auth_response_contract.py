from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileOTPVerifyResponse,
    MobilePrincipalResponse,
    MobileTokenResponse,
    MobileTripClaimSummary,
)


def _tokens() -> MobileTokenResponse:
    now = datetime.now(tz=UTC)
    principal_id = uuid.uuid4()
    return MobileTokenResponse(
        access_token="a" * 64,
        refresh_token="r" * 64,
        access_token_expires_at=now + timedelta(minutes=15),
        refresh_token_expires_at=now + timedelta(days=30),
        session_id=uuid.uuid4(),
        offline_authorization_lease=("a" * 80) + "." + ("b" * 120) + "." + ("c" * 94),
        principal=MobilePrincipalResponse(
            id=principal_id,
            account_id=principal_id,
            principal_type="passenger",
            agency_id=uuid.uuid4(),
            passenger_id=uuid.uuid4(),
            display_name="Contract Passenger",
        ),
    )


def _claim() -> MobileTripClaimSummary:
    return MobileTripClaimSummary(
        claim_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        group_name="Contract Trip",
    )


def test_authenticated_otp_contract_requires_complete_tokens_and_no_claims() -> None:
    tokens = _tokens()
    response = MobileOTPVerifyResponse(
        status="authenticated",
        claims=[],
        tokens=tokens,
    )
    assert response.tokens is tokens

    with pytest.raises(ValidationError):
        MobileOTPVerifyResponse(status="authenticated", claims=[], tokens=None)
    with pytest.raises(ValidationError):
        MobileOTPVerifyResponse(status="authenticated", claims=[_claim()], tokens=tokens)


def test_token_contract_rejects_legacy_response_without_offline_lease() -> None:
    """Guard the production mismatch that surfaced as mobile INVALID_RESPONSE."""

    legacy_payload = _tokens().model_dump()
    removed_lease = legacy_payload.pop("offline_authorization_lease")

    assert isinstance(removed_lease, str)
    with pytest.raises(ValidationError):
        MobileTokenResponse.model_validate(legacy_payload)


def test_pending_otp_contract_never_leaks_tokens_or_unproven_claims() -> None:
    with pytest.raises(ValidationError):
        MobileOTPVerifyResponse(
            status="secondary_verification_required",
            claims=[],
            tokens=_tokens(),
        )
    with pytest.raises(ValidationError):
        MobileOTPVerifyResponse(
            status="secondary_verification_required",
            claims=[_claim()],
            tokens=None,
        )
    with pytest.raises(ValidationError):
        MobileOTPVerifyResponse(
            status="claim_selection_required",
            claims=[],
            tokens=None,
        )

    response = MobileOTPVerifyResponse(
        status="claim_selection_required",
        claims=[_claim()],
        tokens=None,
    )
    assert response.tokens is None
