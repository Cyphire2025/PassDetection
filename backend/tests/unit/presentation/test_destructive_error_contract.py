from __future__ import annotations

import time
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import (
    ConflictError,
    PassportLegalHoldError,
    StepUpRequiredError,
)
from app.presentation.dependencies.auth import require_recent_mfa
from app.presentation.middleware.error_handler import register_exception_handlers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (PassportLegalHoldError(), "PASSPORT_LEGAL_HOLD_ACTIVE"),
        (
            ConflictError(
                "Archive the group before permanent deletion",
                code="GROUP_ARCHIVE_REQUIRED",
            ),
            "GROUP_ARCHIVE_REQUIRED",
        ),
    ],
)
async def test_destructive_conflicts_use_stable_structured_error_envelope(
    error: ConflictError,
    expected_code: str,
) -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/blocked")
    async def blocked() -> None:
        raise error

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/blocked")

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": expected_code,
            "message": error.message,
        }
    }


def _privileged_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.com",
        hashed_password="unused",
        full_name="Agency Admin",
        role=UserRole.AGENCY_ADMIN,
        agency_id=uuid.uuid4(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claims",
    [
        {},
        {"amr": ["password"], "mfa_at": time.time()},
        {"amr": ["totp"], "mfa_at": time.time() - 601},
    ],
)
async def test_destructive_step_up_rejects_missing_or_expired_recent_mfa(
    claims: dict[str, object],
) -> None:
    request = Request({"type": "http", "method": "DELETE", "path": "/"})
    request.state.auth_claims = claims

    with pytest.raises(StepUpRequiredError) as caught:
        await require_recent_mfa(request, _privileged_user())

    assert caught.value.code == "STEP_UP_REQUIRED"


@pytest.mark.asyncio
async def test_destructive_step_up_accepts_current_mfa_for_same_principal() -> None:
    request = Request({"type": "http", "method": "DELETE", "path": "/"})
    request.state.auth_claims = {
        "amr": ["password", "totp"],
        "mfa_at": time.time(),
    }
    user = _privileged_user()

    assert await require_recent_mfa(request, user) is user
