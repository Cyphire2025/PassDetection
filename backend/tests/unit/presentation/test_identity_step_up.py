from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, Request, Response
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.core.security import identity_security
from app.core.security.identity_security import (
    encrypt_mfa_secret,
    generate_mfa_secret,
    identity_mfa_fernet,
    mfa_ciphertext_key_id,
    totp_code,
)
from app.core.security.password import hash_password
from app.infrastructure.database.models import AuditLogModel, UserModel, UserSecurityStateModel
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.security.mfa_step_up_rate_limiter import MFAStepUpLocked
from app.presentation.api.v1.routes import auth_identity
from app.presentation.api.v1.schemas.auth_schemas import MFAStepUpRequest


class _StepUpLimiter:
    lock_failure = False

    async def ensure_available(self, **_kwargs: object) -> None:
        return None

    async def record_failure(self, **_kwargs: object) -> None:
        if self.lock_failure:
            raise MFAStepUpLocked()

    async def clear(self, **_kwargs: object) -> None:
        return None

    async def close(self) -> None:
        return None


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/mfa/step-up",
            "headers": [],
            "client": ("203.0.113.9", 443),
            "scheme": "https",
            "server": ("example.test", 443),
            "query_string": b"",
        }
    )


async def _staff_with_mfa(
    session: AsyncSession,
    *,
    ciphertext: str,
) -> tuple[UserModel, UserSecurityStateModel]:
    user = UserModel(
        email="step-up@example.com",
        hashed_password=hash_password("ExistingPassword9!"),
        full_name="Step Up User",
        role="agency_staff",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    now = datetime.now(tz=UTC)
    state = UserSecurityStateModel(
        user_id=user.id,
        credential_state="active",
        session_version=2,
        mfa_required=True,
        mfa_secret_ciphertext=ciphertext,
        mfa_enabled_at=now,
    )
    session.add(state)
    await session.flush()
    return user, state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lock_failure", "expected_status", "expected_backoff"),
    [(False, 401, False), (True, 429, True)],
)
async def test_failed_step_up_is_audited_with_generic_bounded_error(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    lock_failure: bool,
    expected_status: int,
    expected_backoff: bool,
) -> None:
    secret = generate_mfa_secret()
    user, _ = await _staff_with_mfa(db_session, ciphertext=encrypt_mfa_secret(secret))
    current_user = await UserRepository(db_session).get_by_id(user.id)
    assert current_user is not None
    limiter_type = type(
        "ConfiguredStepUpLimiter",
        (_StepUpLimiter,),
        {"lock_failure": lock_failure},
    )
    monkeypatch.setattr(auth_identity, "MFAStepUpRateLimiter", limiter_type)
    now_counter = int(datetime.now(tz=UTC).timestamp()) // 30
    valid_code = totp_code(secret, counter=now_counter)
    invalid_code = "000001" if valid_code == "000000" else "000000"

    with pytest.raises(HTTPException) as exc_info:
        await auth_identity.step_up_dashboard_session(
            body=MFAStepUpRequest(code=invalid_code),
            request=_request(),
            response=Response(),
            current_user=current_user,
            session=db_session,
        )

    assert exc_info.value.status_code == expected_status
    assert "Verification" in str(exc_info.value.detail)
    audit = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == "auth.step_up_failed")
        )
    ).scalar_one()
    assert audit.result == "failed"
    assert audit.metadata_json == {"temporary_backoff": expected_backoff}


@pytest.mark.asyncio
async def test_successful_step_up_lazily_reencrypts_legacy_mfa_secret(
    db_session: AsyncSession,
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = generate_mfa_secret()
    legacy_ciphertext = (
        identity_mfa_fernet(test_settings).encrypt(secret.encode("ascii")).decode("ascii")
    )
    user, state = await _staff_with_mfa(db_session, ciphertext=legacy_ciphertext)
    current_user = await UserRepository(db_session).get_by_id(user.id)
    assert current_user is not None
    rotated = test_settings.model_copy(
        update={
            "identity_mfa_encryption_key_id": "mfa-2026-08",
            "identity_mfa_encryption_key": SecretStr("new-mfa-encryption-material-2026-08"),
            "identity_mfa_decryption_keys": {"legacy-v1": SecretStr(test_settings.app_secret_key)},
        }
    )
    monkeypatch.setattr(identity_security, "get_settings", lambda: rotated)
    monkeypatch.setattr(auth_identity, "get_settings", lambda: rotated)
    monkeypatch.setattr(auth_identity, "MFAStepUpRateLimiter", _StepUpLimiter)
    counter = int(datetime.now(tz=UTC).timestamp()) // 30

    result = await auth_identity.step_up_dashboard_session(
        body=MFAStepUpRequest(code=totp_code(secret, counter=counter)),
        request=_request(),
        response=Response(),
        current_user=current_user,
        session=db_session,
    )

    assert result.status == "authenticated"
    assert mfa_ciphertext_key_id(state.mfa_secret_ciphertext or "") == "mfa-2026-08"
    assert (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == "auth.step_up_completed")
        )
    ).scalar_one().metadata_json == {"method": "totp"}
