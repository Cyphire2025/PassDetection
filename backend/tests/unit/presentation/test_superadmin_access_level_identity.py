"""Selected roles survive MFA step-up without rewriting the underlying account."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie

import pytest
from fastapi import Response

from app.core.security.access_level import apply_access_level
from app.core.security.identity_security import encrypt_mfa_secret, generate_mfa_secret, totp_code
from app.core.security.jwt import decode_access_token
from app.domain.entities.entities import UserRole
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import auth_identity
from app.presentation.api.v1.schemas.auth_schemas import MFAStepUpRequest
from tests.unit.presentation.test_identity_step_up import _request, _staff_with_mfa, _StepUpLimiter


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.AGENCY_STAFF, UserRole.AGENCY_COORDINATOR])
async def test_mfa_step_up_keeps_effective_response_but_true_token_identity(
    db_session, monkeypatch, role,
):
    secret = generate_mfa_secret()
    model, _ = await _staff_with_mfa(db_session, ciphertext=encrypt_mfa_secret(secret))
    model.role = UserRole.SUPER_ADMIN.value
    await db_session.flush()
    user = await UserRepository(db_session).get_by_id(model.id)
    user = apply_access_level(user, role=role, agency_id=uuid.uuid4(), agency_name="Office")
    request = _request()
    now = datetime.now(tz=UTC)
    deadline = int((now + timedelta(hours=1)).timestamp())
    request.state.auth_claims = {"exp": deadline, "session_exp": deadline}
    monkeypatch.setattr(auth_identity, "MFAStepUpRateLimiter", _StepUpLimiter)
    response = Response()
    result = await auth_identity.step_up_dashboard_session(
        body=MFAStepUpRequest(code=totp_code(secret, counter=int(now.timestamp()) // 30)),
        request=request, response=response, current_user=user, session=db_session,
    )
    assert result.user.id == model.id
    assert result.user.role == role.value
    assert result.user.actual_role == "super_admin"
    assert result.user.can_switch_access_level is True
    cookies = SimpleCookie()
    for header in response.headers.getlist("set-cookie"):
        cookies.load(header)
    claims = decode_access_token(cookies["access_token"].value)
    assert claims["role"] == "super_admin"
    assert claims["agency_id"] is None
    assert claims["session_exp"] == deadline
    await db_session.refresh(model)
    assert model.role == "super_admin"
