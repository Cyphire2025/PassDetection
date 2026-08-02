from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthenticationError
from app.presentation.dependencies import auth as auth_dependencies


@pytest.mark.asyncio
async def test_dashboard_dependency_rejects_client_manager(monkeypatch) -> None:
    user_id = uuid.uuid4()
    user = User.create(
        email="client@example.com",
        hashed_password="unused",
        full_name="Client Manager",
        role=UserRole.CLIENT_MANAGER,
        agency_id=uuid.uuid4(),
    )
    user.id = user_id
    repository = AsyncMock()
    repository.get_by_id.return_value = user
    monkeypatch.setattr(
        auth_dependencies,
        "decode_access_token",
        lambda _token: {"sub": str(user_id)},
    )

    with pytest.raises(AuthenticationError, match="cannot access the dashboard"):
        await auth_dependencies.get_current_user(
            request=SimpleNamespace(cookies={}),
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="legacy-dashboard-token"
            ),
            user_repo=repository,
        )
