"""Recovery-code rotation preserves existing assurance without inventing MFA."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.security.jwt import create_access_token, decode_access_token
from app.infrastructure.database.models import RefreshTokenModel, UserModel, UserSecurityStateModel
from tests.integration.test_auth_response_durability import auth_database as auth_database
from tests.integration.test_auth_response_durability import prepare_request


@pytest.mark.parametrize("verified_factor", [True, False])
async def test_rotation_preserves_signed_mfa_time_and_password_only_role_policy(
    auth_database,
    verified_factor,
):
    env = auth_database
    path, headers, _ = await prepare_request(env.sessions, "regenerate_codes")
    original = decode_access_token(
        next(value.decode()[7:] for name, value in headers if name == b"authorization")
    )
    prior_verification = datetime.now(UTC) - timedelta(minutes=5) if verified_factor else None
    role = "agency_staff" if verified_factor else "agency_coordinator"
    async with env.sessions() as session, session.begin():
        user = await session.scalar(select(UserModel))
        user.role = role
        user.created_at = user.updated_at = datetime.now(UTC) - timedelta(days=1)
        state = await session.scalar(select(UserSecurityStateModel))
        state.mfa_required = verified_factor
        state.mfa_enabled_at = datetime.now(UTC) - timedelta(days=1)
        credential = await session.scalar(select(RefreshTokenModel))
        credential.mfa_authenticated_at = prior_verification
        credential.authentication_methods = "pwd,totp" if verified_factor else "pwd"
    access, _ = create_access_token(
        uuid.UUID(original["sub"]),
        role,
        None,
        session_version=original["sv"],
        session_id=uuid.UUID(original["sid"]),
        authentication_methods=("pwd", "totp") if verified_factor else ("pwd",),
        mfa_authenticated_at=prior_verification,
        session_expires_at=datetime.fromtimestamp(original["session_exp"], UTC),
    )
    env.gate.release.set()
    async with AsyncClient(
        transport=ASGITransport(app=env.app),
        base_url="http://testserver",
    ) as client:
        response = await client.post(path, headers={"Authorization": f"Bearer {access}"})
        assert response.status_code == 200
        replacement = decode_access_token(client.cookies["access_token"])
    assert replacement["session_exp"] == original["session_exp"]
    if verified_factor:
        assert replacement["mfa_at"] == int(prior_verification.timestamp())
        assert replacement["amr"] == ["pwd", "totp"]
    else:
        assert "mfa_at" not in replacement
        assert replacement["amr"] == ["pwd"]
