from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)


def _sql(statement) -> str:  # type: ignore[no-untyped-def]
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_group_summary_query_applies_server_filters_and_safe_archived_scope() -> None:
    repository = PassportSubmissionRepository(AsyncMock())

    statement = repository._group_summary_statement(
        uuid.uuid4(),
        group_status="archived",
        review_filter="needs_review",
        search="Liberty",
        destination="Phuket",
        exclude_archived_groups=False,
    )
    sql = _sql(statement)

    assert "client_groups.status = 'archived'" in sql
    assert "client_groups.status != 'deleted'" in sql
    assert "client_groups.deleted_at IS NULL" in sql
    assert "lower(client_groups.name) LIKE" in sql
    assert "lower(coalesce(client_groups.destination" in sql
    assert "HAVING" in sql
    assert "ESCAPE" in sql


def test_default_group_summary_query_excludes_archived_and_soft_deleted_groups() -> None:
    repository = PassportSubmissionRepository(AsyncMock())

    sql = _sql(
        repository._group_summary_statement(
            uuid.uuid4(),
            group_id=uuid.uuid4(),
        )
    )

    assert "client_groups.status NOT IN ('archived', 'deleted')" in sql
    assert "client_groups.deleted_at IS NULL" in sql


def test_group_summary_count_projection_groups_only_by_group_id() -> None:
    repository = PassportSubmissionRepository(AsyncMock())
    statement = repository._group_summary_statement(
        uuid.uuid4(),
        review_filter="confirmed_only",
    )
    count_source = (
        statement
        .with_only_columns(ClientGroupModel.id)
        .group_by(None)
        .group_by(ClientGroupModel.id)
    )
    count_statement = select(func.count()).select_from(count_source.subquery())
    sql = _sql(count_statement)

    assert "SELECT client_groups.id" in sql
    assert "GROUP BY client_groups.id" in sql
    assert "client_groups.notes" not in sql
    assert "HAVING" in sql


def test_group_summary_join_includes_failed_submissions_in_its_counts() -> None:
    repository = PassportSubmissionRepository(AsyncMock())

    statement = repository._group_summary_statement(uuid.uuid4())
    sql = _sql(statement)
    join_clause = sql.split(" ON ", maxsplit=1)[1].split(" WHERE", maxsplit=1)[0]

    assert "'failed'" in join_clause


class _EmptyScalarResult:
    def scalars(self):  # type: ignore[no-untyped-def]
        return self

    def all(self) -> list[object]:
        return []


@pytest.mark.asyncio
async def test_default_group_submission_query_excludes_historical_groups() -> None:
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_EmptyScalarResult())
    )

    await PassportSubmissionRepository(session).list_by_group(
        uuid.uuid4(),
        uuid.uuid4(),
        exclude_archived_groups=True,
    )

    sql = _sql(session.execute.await_args.args[0])
    assert "client_groups.status NOT IN ('archived', 'deleted')" in sql
    assert "client_groups.deleted_at IS NULL" in sql


@pytest.mark.asyncio
async def test_archived_group_submission_query_keeps_tenant_and_staff_scopes() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    user = User(
        id=uuid.uuid4(),
        email="staff@example.com",
        hashed_password="unused",
        full_name="Agency Staff",
        role=UserRole.AGENCY_STAFF,
        agency_id=agency_id,
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_EmptyScalarResult())
    )

    await PassportSubmissionRepository(session).list_by_group(
        agency_id,
        group_id,
        include_archived_group=True,
        created_by_user_id=user.id,
        visible_to_user=user,
    )

    sql = _sql(session.execute.await_args.args[0])
    assert f"passport_submissions.agency_id = '{agency_id}'" in sql
    assert f"passport_submissions.group_id = '{group_id}'" in sql
    assert "client_groups.status != 'deleted'" in sql
    assert "client_groups.deleted_at IS NULL" in sql
    assert f"manager_group_access.manager_id = '{user.id}'" in sql
    assert f"client_groups.created_by_user_id = '{user.id}'" in sql
    assert "passport_submissions.group_id IN (SELECT client_groups.id" in sql
