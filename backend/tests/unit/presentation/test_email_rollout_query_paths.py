"""Ordinary target pagination, visibility, empty states and update conflicts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_ai_models import EmailAiRolloutPolicyModel
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import AgencyModel, UserModel
from app.presentation.api.v1.routes import email_ai_rollout_admin as rollout
from app.presentation.api.v1.schemas.email_ai_schemas import UpdateEmailAiRolloutPolicyRequest


@pytest.fixture
async def targets(db_session, monkeypatch):
    agencies = [
        AgencyModel(id=uuid.uuid4(), name=f"Agency {i}", email=f"agency-{i}@example.test")
        for i in range(3)
    ]
    db_session.add_all(agencies)
    await db_session.flush()
    admin_id = uuid.uuid4()
    admin = UserModel(
        id=admin_id,
        email="admin@example.test",
        full_name="Administrator",
        role="super_admin",
        hashed_password="unused",
    )
    staff = [
        UserModel(
            id=uuid.uuid4(),
            agency_id=agencies[i].id,
            email=f"staff-{i}@example.test",
            full_name=f"Staff {i}",
            role="agency_staff",
            hashed_password="unused",
        )
        for i in range(3)
    ]
    db_session.add_all([admin, *staff])
    await db_session.flush()
    connections = [
        EmailConnectionModel(
            agency_id=a.id,
            owner_user_id=admin_id,
            provider="gmail",
            provider_account_id=f"account-{i}",
            email_address=f"mailbox-{i}@example.test",
        )
        for i, a in enumerate(agencies)
    ]
    db_session.add_all(connections)
    await db_session.flush()
    settings = SimpleNamespace(email_ai_enabled=True, email_ai_notifications_enabled=False)
    monkeypatch.setattr(rollout, "get_settings", lambda: settings)
    return SimpleNamespace(
        agencies=agencies,
        staff=staff,
        connections=connections,
        admin=User(
            id=admin_id,
            email=admin.email,
            full_name=admin.full_name,
            role=UserRole.SUPER_ADMIN,
            hashed_password="unused",
            agency_id=None,
        ),
    )


@pytest.mark.parametrize("scope", ["agency", "user", "connection"])
async def test_target_queries_keep_stable_offset_and_specific_scope_filters(
    db_session, targets, scope
):
    expected = (
        targets.agencies
        if scope == "agency"
        else targets.staff
        if scope == "user"
        else targets.connections
    )
    page = await rollout._target_rows(
        db_session, scope_type=scope, limit=1, offset=1, requesting_user_id=targets.admin.id
    )
    assert [row.target_id for row in page] == [expected[1].id]
    specific = await rollout._target_rows(
        db_session,
        scope_type=scope,
        limit=2,
        agency_id=targets.agencies[1].id,
        target_id=expected[1].id,
        search="1",
        requesting_user_id=targets.admin.id,
    )
    assert [row.target_id for row in specific] == [expected[1].id]
    absent = await rollout._target_rows(
        db_session,
        scope_type=scope,
        limit=2,
        agency_id=targets.agencies[0].id,
        target_id=expected[1].id,
        requesting_user_id=targets.admin.id,
    )
    assert absent == []


async def test_user_and_connection_queries_exclude_inactive_and_non_office_actors(
    db_session, targets
):
    targets.staff[0].is_active = False
    targets.staff[1].role = "coordinator"
    targets.connections[0].status = "disconnected"
    targets.connections[0].disconnected_at = datetime.now(UTC)
    await db_session.flush()
    users = await rollout._target_rows(
        db_session, scope_type="user", limit=20, requesting_user_id=targets.admin.id
    )
    assert [row.target_id for row in users] == [targets.staff[2].id]
    connections = await rollout._target_rows(
        db_session, scope_type="connection", limit=20, requesting_user_id=targets.admin.id
    )
    assert [row.target_id for row in connections] == [row.id for row in targets.connections[1:]]
    hidden = await rollout._target_rows(
        db_session, scope_type="connection", limit=20, requesting_user_id=targets.staff[2].id
    )
    assert hidden == []


@pytest.mark.parametrize("field,value", [("is_active", False), ("role", "coordinator")])
async def test_connection_queries_require_a_current_office_owner(db_session, targets, field, value):
    owner = await db_session.get(UserModel, targets.admin.id)
    setattr(owner, field, value)
    await db_session.flush()
    assert (
        await rollout._target_rows(
            db_session, scope_type="connection", limit=20, requesting_user_id=targets.admin.id
        )
        == []
    )


async def test_empty_normalized_search_returns_no_targets_or_policy_rows(db_session, targets):
    result = await rollout.list_email_ai_rollout_targets(
        scope_type="agency",
        search=" No such  agency ",
        current_user=targets.admin,
        session=db_session,
    )
    assert result.items == [] and result.truncated is False


async def test_target_listing_has_a_bounded_two_hundred_item_response(db_session, targets):
    db_session.add_all(
        [AgencyModel(name=f"Extra {i:03}", email=f"extra-{i}@example.test") for i in range(200)]
    )
    await db_session.flush()
    result = await rollout.list_email_ai_rollout_targets(
        scope_type="agency", search=None, current_user=targets.admin, session=db_session
    )
    assert len(result.items) == 200 and result.truncated is True
    assert [row.label for row in result.items][:3] == ["Agency 0", "Agency 1", "Agency 2"]


@pytest.mark.parametrize("scope", ["agency", "user"])
async def test_updating_ancestor_policy_keeps_exact_scope_and_effective_deny(
    db_session, targets, scope
):
    target = targets.agencies[0] if scope == "agency" else targets.staff[0]
    result = await rollout.update_email_ai_rollout_policy(
        payload=UpdateEmailAiRolloutPolicyRequest(
            scope_type=scope, agency_id=targets.agencies[0].id, target_id=target.id, enabled=False
        ),
        current_user=targets.admin,
        session=db_session,
    )
    assert result.direct_enabled is False and result.effective_enabled is False
    assert result.scope_type == scope and result.connection_id is None
    assert result.owner_user_id == (None if scope == "agency" else targets.staff[0].id)


async def test_namespace_loss_rejects_update_before_writing_a_policy(
    db_session, targets, monkeypatch
):
    lock = AsyncMock(return_value=False)
    monkeypatch.setattr(rollout, "lock_email_ai_policy_namespace", lock)
    with pytest.raises(HTTPException) as error:
        await rollout.update_email_ai_rollout_policy(
            payload=UpdateEmailAiRolloutPolicyRequest(
                scope_type="agency",
                agency_id=targets.agencies[0].id,
                target_id=targets.agencies[0].id,
                enabled=False,
            ),
            current_user=targets.admin,
            session=db_session,
        )
    assert error.value.status_code == 404
    lock.assert_awaited_once_with(db_session, agency_id=targets.agencies[0].id)


async def test_missing_previous_revision_rejects_a_new_policy(db_session, targets):
    with pytest.raises(HTTPException) as error:
        await rollout.update_email_ai_rollout_policy(
            payload=UpdateEmailAiRolloutPolicyRequest(
                scope_type="agency",
                agency_id=targets.agencies[0].id,
                target_id=targets.agencies[0].id,
                enabled=False,
                expected_updated_at=datetime.now(UTC),
            ),
            current_user=targets.admin,
            session=db_session,
        )
    assert error.value.status_code == 409


async def test_existing_policy_requires_an_expected_timestamp(db_session, targets):
    db_session.add(
        EmailAiRolloutPolicyModel(
            agency_id=targets.agencies[0].id,
            scope_type="agency",
            enabled=True,
            updated_by_user_id=targets.admin.id,
        )
    )
    await db_session.flush()
    with pytest.raises(HTTPException) as error:
        await rollout.update_email_ai_rollout_policy(
            payload=UpdateEmailAiRolloutPolicyRequest(
                scope_type="agency",
                agency_id=targets.agencies[0].id,
                target_id=targets.agencies[0].id,
                enabled=False,
            ),
            current_user=targets.admin,
            session=db_session,
        )
    assert error.value.status_code == 409


async def test_actual_mcp_reader_uses_the_same_owner_query_mapping_and_next_offset(
    db_session, targets, monkeypatch
):
    from app.core.config import settings
    from app.presentation.mcp.dashboard_read_adapters import email_ai_rollout

    monkeypatch.setattr(
        settings,
        "get_settings",
        lambda: SimpleNamespace(email_ai_enabled=True, email_ai_notifications_enabled=False),
    )
    page = await email_ai_rollout(
        scope_type="connection",
        current_user=targets.admin,
        session=db_session,
        search=" MAILBOX  ",
        offset=1,
        limit=1,
    )
    assert page["global_enabled"] is True
    assert page["offset"] == 1 and page["limit"] == 1
    assert page["has_more"] is True and page["next_offset"] == 2
    assert len(page["items"]) == 1
    assert page["items"][0].target_id == targets.connections[1].id
