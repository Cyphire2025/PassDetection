from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.email.deadline_notification_visibility import _visible_linked_group_name
from app.infrastructure.repositories.user_repository import UserRepository


@pytest.mark.parametrize("linked_id", [None, 42, "not-a-group-id"])
async def test_non_group_references_never_load_an_owner(monkeypatch, linked_id) -> None:
    get_owner = AsyncMock()
    monkeypatch.setattr(UserRepository, "get_by_id", get_owner)
    analysis = EmailAiAnalysisModel(result_json={"linked_group_id": linked_id})

    assert await _visible_linked_group_name(SimpleNamespace(), analysis) is None

    get_owner.assert_not_awaited()


@pytest.mark.parametrize("owner_state", ["missing", "inactive", "other-agency"])
async def test_unavailable_current_owner_never_loads_the_linked_group(
    monkeypatch, owner_state: str
) -> None:
    agency = uuid.UUID(int=1)
    owner = User(
        uuid.UUID(int=2),
        "owner@example.test",
        "unused",
        "Owner",
        UserRole.AGENCY_STAFF,
        agency,
        is_active=owner_state != "inactive",
    )
    if owner_state == "other-agency":
        owner.agency_id = uuid.UUID(int=3)
    get_owner = AsyncMock(return_value=None if owner_state == "missing" else owner)
    monkeypatch.setattr(UserRepository, "get_by_id", get_owner)
    session = SimpleNamespace(scalar=AsyncMock())
    analysis = EmailAiAnalysisModel(
        agency_id=agency,
        owner_user_id=owner.id,
        result_json={"linked_group_id": str(uuid.UUID(int=4))},
    )

    assert await _visible_linked_group_name(session, analysis) is None

    get_owner.assert_awaited_once_with(owner.id)
    session.scalar.assert_not_awaited()
