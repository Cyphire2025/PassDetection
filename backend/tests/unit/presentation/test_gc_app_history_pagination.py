from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes.gc_app import (
    list_client_manager_audit,
    list_client_manager_sessions,
)
from app.presentation.api.v1.routes.gc_app_content import list_group_gc_audit
from app.presentation.api.v1.schemas.gc_app_schemas import (
    GCAppAuditPageResponse,
    GCAppAuditResponse,
)


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def first(self) -> object:
        return self._value

    def scalars(self) -> object:
        return self._value


def _current_user(agency_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="gc-admin@example.test",
        role=UserRole.AGENCY_ADMIN,
        agency_id=agency_id,
    )


def _compiled(statement: object) -> str:
    return str(
        statement.compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _audit_rows(count: int, *, entity_id: uuid.UUID) -> list[SimpleNamespace]:
    now = datetime.now(tz=UTC)
    return [
        SimpleNamespace(
            id=uuid.uuid4(),
            action="gc_app.history_tested",
            entity_type="client_manager_profile",
            entity_id=str(entity_id),
            actor_email="gc-admin@example.test",
            metadata_json={"position": index},
            created_at=now - timedelta(seconds=index),
        )
        for index in range(count)
    ]


def test_history_page_envelopes_reject_more_than_the_endpoint_limit() -> None:
    event = GCAppAuditResponse(
        id=uuid.uuid4(),
        action="gc_app.history_tested",
        entity_type="client_manager_profile",
        entity_id=str(uuid.uuid4()),
        actor_email="gc-admin@example.test",
        metadata={},
        created_at=datetime.now(tz=UTC),
    )

    with pytest.raises(ValidationError, match="List should have at most 100 items"):
        GCAppAuditPageResponse(
            items=[event] * 101,
            total=101,
            offset=0,
            limit=100,
        )


@pytest.mark.asyncio
async def test_client_manager_sessions_are_deterministically_paginated_in_three_queries() -> None:
    agency_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    items = [
        SimpleNamespace(
            id=uuid.uuid4(),
            platform="android",
            app_version="1.2.3",
            status="active",
            last_seen_at=now - timedelta(minutes=index),
            created_at=now - timedelta(days=index),
            expires_at=now + timedelta(days=7),
            revoked_at=None,
        )
        for index in range(25)
    ]
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(
                    (
                        SimpleNamespace(id=profile_id),
                        SimpleNamespace(id=user_id),
                        SimpleNamespace(id=uuid.uuid4()),
                    )
                ),
                _Result(items),
            ]
        ),
        scalar=AsyncMock(return_value=73),
    )

    response = await list_client_manager_sessions(
        profile_id=profile_id,
        agency_id=None,
        offset=25,
        limit=25,
        current_user=_current_user(agency_id),
        session=session,  # type: ignore[arg-type]
    )

    assert response.total == 73
    assert response.offset == 25
    assert response.limit == 25
    assert len(response.items) == 25
    assert session.execute.await_count == 2
    assert session.scalar.await_count == 1
    history_sql = _compiled(session.execute.await_args_list[1].args[0])
    assert "LIMIT 25 OFFSET 25" in history_sql
    assert "mobile_device_sessions.created_at DESC, mobile_device_sessions.id DESC" in history_sql
    assert str(agency_id) in history_sql
    assert str(user_id) in history_sql


@pytest.mark.asyncio
async def test_client_manager_audit_is_deterministically_paginated_in_three_queries() -> None:
    agency_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    rows = _audit_rows(25, entity_id=profile_id)
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(
                    (
                        SimpleNamespace(id=profile_id),
                        SimpleNamespace(id=uuid.uuid4()),
                        SimpleNamespace(id=uuid.uuid4()),
                    )
                ),
                _Result(rows),
            ]
        ),
        scalar=AsyncMock(return_value=64),
    )

    response = await list_client_manager_audit(
        profile_id=profile_id,
        agency_id=None,
        offset=25,
        limit=25,
        current_user=_current_user(agency_id),
        session=session,  # type: ignore[arg-type]
    )

    assert response.total == 64
    assert response.offset == 25
    assert response.limit == 25
    assert len(response.items) == 25
    assert session.execute.await_count == 2
    assert session.scalar.await_count == 1
    history_sql = _compiled(session.execute.await_args_list[1].args[0])
    assert "LIMIT 25 OFFSET 25" in history_sql
    assert "audit_logs.created_at DESC, audit_logs.id DESC" in history_sql
    assert "audit_logs.entity_type = 'client_manager_profile'" in history_sql
    assert str(profile_id) in history_sql


@pytest.mark.asyncio
async def test_group_audit_is_deterministically_paginated_in_three_queries() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    access_id = uuid.uuid4()
    rows = _audit_rows(50, entity_id=access_id)
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(
                    (
                        SimpleNamespace(id=access_id, agency_id=agency_id),
                        SimpleNamespace(id=group_id, agency_id=agency_id),
                    )
                ),
                _Result(rows),
            ]
        ),
        scalar=AsyncMock(return_value=151),
    )

    response = await list_group_gc_audit(
        group_id=group_id,
        offset=100,
        limit=50,
        agency_id=None,
        current_user=_current_user(agency_id),
        session=session,  # type: ignore[arg-type]
    )

    assert response.total == 151
    assert response.offset == 100
    assert response.limit == 50
    assert len(response.items) == 50
    assert session.execute.await_count == 2
    assert session.scalar.await_count == 1
    history_sql = _compiled(session.execute.await_args_list[1].args[0])
    assert "LIMIT 50 OFFSET 100" in history_sql
    assert "audit_logs.created_at DESC, audit_logs.id DESC" in history_sql
    assert "audit_logs.action LIKE 'gc_app.%%'" in history_sql
    assert str(agency_id) in history_sql
