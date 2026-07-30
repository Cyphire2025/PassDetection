from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_ai_models import (
    EmailAiRolloutPolicyModel,
)
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    UserModel,
)
from app.presentation.api.v1.routes import email_ai_rollout_admin
from app.presentation.api.v1.routes.email_ai_rollout_admin import (
    list_email_ai_rollout_targets,
    update_email_ai_rollout_policy,
)
from app.presentation.api.v1.schemas.email_ai_schemas import (
    UpdateEmailAiRolloutPolicyRequest,
)


def _admin(user_id: uuid.UUID) -> User:
    return User(
        id=user_id,
        email="rollout-admin@example.test",
        hashed_password="not-used",
        full_name="Rollout Admin",
        role=UserRole.SUPER_ADMIN,
        agency_id=None,
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _settings(monkeypatch, *, enabled: bool = True) -> SimpleNamespace:
    settings = SimpleNamespace(
        email_ai_enabled=enabled,
        email_ai_notifications_enabled=False,
    )
    monkeypatch.setattr(
        email_ai_rollout_admin,
        "get_settings",
        lambda: settings,
    )
    return settings


async def _seed_targets(db_session) -> SimpleNamespace:
    admin_id = uuid.uuid4()
    first_agency_id = uuid.uuid4()
    second_agency_id = uuid.uuid4()
    first_owner_id = uuid.uuid4()
    second_owner_id = uuid.uuid4()
    db_session.add_all(
        [
            AgencyModel(
                id=first_agency_id,
                name="Alpha Travel",
                email="alpha-rollout@example.test",
                is_active=True,
            ),
            AgencyModel(
                id=second_agency_id,
                name="Beta Travel",
                email="beta-rollout@example.test",
                is_active=True,
            ),
            UserModel(
                id=admin_id,
                email="rollout-admin@example.test",
                hashed_password="not-used",
                full_name="Rollout Admin",
                role=UserRole.SUPER_ADMIN.value,
                agency_id=None,
                is_active=True,
            ),
            UserModel(
                id=first_owner_id,
                email="alpha-owner@example.test",
                hashed_password="not-used",
                full_name="Alpha Owner",
                role=UserRole.AGENCY_STAFF.value,
                agency_id=first_agency_id,
                is_active=True,
            ),
            UserModel(
                id=second_owner_id,
                email="beta-owner@example.test",
                hashed_password="not-used",
                full_name="Beta Owner",
                role=UserRole.AGENCY_MANAGER.value,
                agency_id=second_agency_id,
                is_active=True,
            ),
        ]
    )
    await db_session.flush()
    first_connection = EmailConnectionModel(
        agency_id=first_agency_id,
        owner_user_id=first_owner_id,
        provider="gmail",
        provider_account_id="alpha-rollout-provider",
        email_address="alpha-owner@example.test",
        status="active",
        ai_processing_enabled=True,
        ai_enabled_at=datetime.now(tz=UTC),
        created_by_user_id=first_owner_id,
    )
    second_connection = EmailConnectionModel(
        agency_id=second_agency_id,
        owner_user_id=second_owner_id,
        provider="outlook",
        provider_account_id="beta-rollout-provider",
        email_address="beta-owner@example.test",
        status="active",
        ai_processing_enabled=True,
        ai_enabled_at=datetime.now(tz=UTC),
        created_by_user_id=second_owner_id,
    )
    admin_connection = EmailConnectionModel(
        agency_id=first_agency_id,
        owner_user_id=admin_id,
        provider="outlook",
        provider_account_id="admin-rollout-provider",
        email_address="rollout-admin@example.test",
        status="active",
        ai_processing_enabled=True,
        ai_enabled_at=datetime.now(tz=UTC),
        created_by_user_id=admin_id,
    )
    db_session.add_all(
        [first_connection, second_connection, admin_connection]
    )
    await db_session.flush()
    return SimpleNamespace(
        admin_id=admin_id,
        first_agency_id=first_agency_id,
        second_agency_id=second_agency_id,
        first_owner_id=first_owner_id,
        second_owner_id=second_owner_id,
        first_connection_id=first_connection.id,
        second_connection_id=second_connection.id,
        admin_connection_id=admin_connection.id,
    )


@pytest.mark.asyncio
async def test_rollout_target_listing_exposes_each_scope_and_fail_closed_chain(
    db_session,
    monkeypatch,
) -> None:
    graph = await _seed_targets(db_session)
    settings = _settings(monkeypatch)
    db_session.add_all(
        [
            EmailAiRolloutPolicyModel(
                agency_id=graph.first_agency_id,
                scope_type="agency",
                enabled=False,
                updated_by_user_id=graph.admin_id,
            ),
            EmailAiRolloutPolicyModel(
                agency_id=graph.first_agency_id,
                owner_user_id=graph.first_owner_id,
                scope_type="user",
                enabled=True,
                updated_by_user_id=graph.admin_id,
            ),
            EmailAiRolloutPolicyModel(
                agency_id=graph.first_agency_id,
                owner_user_id=graph.admin_id,
                connection_id=graph.admin_connection_id,
                scope_type="connection",
                enabled=True,
                updated_by_user_id=graph.admin_id,
            ),
        ]
    )
    await db_session.flush()
    current_user = _admin(graph.admin_id)

    agencies = await list_email_ai_rollout_targets(
        scope_type="agency",
        search=None,
        current_user=current_user,
        session=db_session,
    )
    users = await list_email_ai_rollout_targets(
        scope_type="user",
        search=None,
        current_user=current_user,
        session=db_session,
    )
    connections = await list_email_ai_rollout_targets(
        scope_type="connection",
        search=None,
        current_user=current_user,
        session=db_session,
    )

    agency_items = {item.target_id: item for item in agencies.items}
    user_items = {
        (item.agency_id, item.target_id): item for item in users.items
    }
    connection_items = {
        item.target_id: item for item in connections.items
    }
    assert set(agency_items) == {
        graph.first_agency_id,
        graph.second_agency_id,
    }
    assert set(user_items) == {
        (graph.first_agency_id, graph.first_owner_id),
        (graph.second_agency_id, graph.second_owner_id),
    }
    assert set(connection_items) == {graph.admin_connection_id}
    assert agencies.global_enabled is True
    assert agencies.global_notifications_enabled is False
    assert agencies.truncated is False

    assert agency_items[graph.first_agency_id].direct_enabled is False
    assert agency_items[graph.first_agency_id].effective_enabled is False
    assert (
        user_items[
            (graph.first_agency_id, graph.first_owner_id)
        ].direct_enabled
        is True
    )
    assert (
        user_items[
            (graph.first_agency_id, graph.first_owner_id)
        ].effective_enabled
        is False
    )
    assert (
        connection_items[graph.admin_connection_id].direct_enabled is True
    )
    assert (
        connection_items[graph.admin_connection_id].effective_enabled is False
    )
    assert (
        connection_items[graph.admin_connection_id].owner_user_id
        == graph.admin_id
    )
    assert (
        connection_items[graph.admin_connection_id].connection_id
        == graph.admin_connection_id
    )

    assert agency_items[graph.second_agency_id].direct_enabled is None
    assert agency_items[graph.second_agency_id].effective_enabled is True
    assert (
        user_items[
            (graph.second_agency_id, graph.second_owner_id)
        ].effective_enabled
        is True
    )
    assert graph.first_connection_id not in connection_items
    assert graph.second_connection_id not in connection_items
    assert {
        item.label for item in connection_items.values()
    } == {"rollout-admin@example.test"}

    settings.email_ai_enabled = False
    globally_disabled = await list_email_ai_rollout_targets(
        scope_type="connection",
        search=None,
        current_user=current_user,
        session=db_session,
    )
    assert globally_disabled.global_enabled is False
    assert all(
        item.effective_enabled is False
        for item in globally_disabled.items
    )


@pytest.mark.asyncio
async def test_rollout_update_rejects_spoofed_target_relationships(
    db_session,
    monkeypatch,
) -> None:
    graph = await _seed_targets(db_session)
    _settings(monkeypatch)
    current_user = _admin(graph.admin_id)

    for payload in (
        UpdateEmailAiRolloutPolicyRequest(
            scope_type="user",
            target_id=graph.first_owner_id,
            agency_id=graph.second_agency_id,
            enabled=False,
        ),
        UpdateEmailAiRolloutPolicyRequest(
            scope_type="connection",
            target_id=graph.first_connection_id,
            agency_id=graph.second_agency_id,
            enabled=False,
        ),
        UpdateEmailAiRolloutPolicyRequest(
            scope_type="connection",
            target_id=graph.first_connection_id,
            agency_id=graph.first_agency_id,
            enabled=False,
        ),
    ):
        with pytest.raises(HTTPException) as caught:
            await update_email_ai_rollout_policy(
                payload=payload,
                current_user=current_user,
                session=db_session,
            )
        assert caught.value.status_code == 404

    policies = list(
        (
            await db_session.execute(
                select(EmailAiRolloutPolicyModel)
            )
        ).scalars()
    )
    assert policies == []


@pytest.mark.asyncio
async def test_rollout_update_is_revision_safe_and_audited(
    db_session,
    monkeypatch,
) -> None:
    graph = await _seed_targets(db_session)
    _settings(monkeypatch)
    current_user = _admin(graph.admin_id)
    target = graph.admin_connection_id

    created = await update_email_ai_rollout_policy(
        payload=UpdateEmailAiRolloutPolicyRequest(
            scope_type="connection",
            target_id=target,
            agency_id=graph.first_agency_id,
            enabled=False,
        ),
        current_user=current_user,
        session=db_session,
    )
    assert created.direct_enabled is False
    assert created.effective_enabled is False
    assert created.updated_at is not None

    with pytest.raises(HTTPException) as stale:
        await update_email_ai_rollout_policy(
            payload=UpdateEmailAiRolloutPolicyRequest(
                scope_type="connection",
                target_id=target,
                agency_id=graph.first_agency_id,
                enabled=True,
                expected_updated_at=(
                    _aware(created.updated_at) - timedelta(seconds=1)
                ),
            ),
            current_user=current_user,
            session=db_session,
        )
    assert stale.value.status_code == 409

    updated = await update_email_ai_rollout_policy(
        payload=UpdateEmailAiRolloutPolicyRequest(
            scope_type="connection",
            target_id=target,
            agency_id=graph.first_agency_id,
            enabled=True,
            expected_updated_at=_aware(created.updated_at),
        ),
        current_user=current_user,
        session=db_session,
    )
    assert updated.direct_enabled is True
    assert updated.effective_enabled is True
    assert updated.updated_at is not None
    assert _aware(updated.updated_at) >= _aware(created.updated_at)

    policy = (
        await db_session.execute(
            select(EmailAiRolloutPolicyModel).where(
                EmailAiRolloutPolicyModel.connection_id == target
            )
        )
    ).scalar_one()
    assert policy.enabled is True
    assert policy.updated_by_user_id == graph.admin_id

    audit_rows = list(
        (
            await db_session.execute(
                select(AuditLogModel)
                .where(
                    AuditLogModel.action
                    == "email_ai_rollout_policy_updated",
                    AuditLogModel.entity_id == str(policy.id),
                )
                .order_by(AuditLogModel.created_at.asc())
            )
        ).scalars()
    )
    assert len(audit_rows) == 2
    assert audit_rows[0].agency_id == graph.first_agency_id
    assert audit_rows[0].user_id == graph.admin_id
    assert audit_rows[0].metadata_json == {
        "scope_type": "connection",
        "target_id": str(target),
        "owner_user_id": str(graph.admin_id),
        "connection_id": str(target),
        "old_enabled": None,
        "new_enabled": False,
    }
    assert audit_rows[1].metadata_json["old_enabled"] is False
    assert audit_rows[1].metadata_json["new_enabled"] is True
