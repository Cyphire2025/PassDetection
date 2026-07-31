from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from app.application.dtos.passport_dtos import (
    PassportGroupSummaryDTO,
    PassportGroupSummaryPageDTO,
)
from app.domain.entities.entities import User, UserRole
from app.presentation.api.v1.routes import passports
from app.presentation.dependencies.auth import get_current_active_user


def _user(
    agency_id: uuid.UUID,
    *,
    role: UserRole = UserRole.AGENCY_ADMIN,
) -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.com",
        hashed_password="unused",
        full_name="Agency Admin",
        role=role,
        agency_id=agency_id,
    )


def _summary(group_id: uuid.UUID) -> PassportGroupSummaryDTO:
    return PassportGroupSummaryDTO(
        group_id=group_id,
        group_name="Group 51",
        group_status="active",
        total_passports=4,
        pending_review_count=1,
        confirmed_count=3,
        failed_count=0,
        latest_submission_at=datetime(2026, 7, 31, tzinfo=UTC),
        destination="Phuket",
        departure_cities=[],
    )


@pytest.fixture
async def summary_client():
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    use_case = AsyncMock()
    use_case.execute_page.return_value = PassportGroupSummaryPageDTO(
        items=[_summary(group_id)],
        total=51,
        page=2,
        page_size=50,
    )
    use_case.execute_one.return_value = _summary(group_id)

    app = FastAPI()
    app.include_router(passports.router, prefix="/api/v1/passports")
    app.dependency_overrides[get_current_active_user] = lambda: _user(agency_id)
    app.dependency_overrides[
        passports._get_list_passport_groups_use_case
    ] = lambda: use_case

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client, use_case, group_id


@pytest.mark.asyncio
async def test_paginated_group_summary_route_returns_total_and_forwards_filters(
    summary_client,
) -> None:
    client, use_case, _group_id = summary_client

    response = await client.get(
        "/api/v1/passports/groups/summaries",
        params={
            "page": 2,
            "page_size": 50,
            "group_status": "active",
            "review_filter": "needs_review",
            "search": "Group",
            "destination": "Phuket",
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 51
    assert response.json()["total_pages"] == 2
    assert response.json()["items"][0]["group_name"] == "Group 51"
    use_case.execute_page.assert_awaited_once()
    call = use_case.execute_page.await_args.kwargs
    assert call["page"] == 2
    assert call["page_size"] == 50
    assert call["group_status"] == "active"
    assert call["review_filter"] == "needs_review"
    assert call["destination"] == "Phuket"


@pytest.mark.asyncio
async def test_group_summary_routes_reject_unbounded_page_sizes(
    summary_client,
) -> None:
    client, use_case, _group_id = summary_client

    paginated = await client.get(
        "/api/v1/passports/groups/summaries",
        params={"page_size": 201},
    )
    compatibility = await client.get(
        "/api/v1/passports/groups",
        params={"limit": 201},
    )

    assert paginated.status_code == 422
    assert compatibility.status_code == 422
    use_case.execute_page.assert_not_awaited()
    use_case.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_archived_filter_explicitly_includes_archived_but_not_deleted_groups(
    summary_client,
) -> None:
    client, use_case, _group_id = summary_client

    response = await client.get(
        "/api/v1/passports/groups/summaries",
        params={"group_status": "archived"},
    )

    assert response.status_code == 200
    call = use_case.execute_page.await_args.kwargs
    assert call["group_status"] == "archived"
    assert call["include_archived"] is True


@pytest.mark.asyncio
async def test_single_group_summary_route_does_not_depend_on_the_list_page(
    summary_client,
) -> None:
    client, use_case, group_id = summary_client

    response = await client.get(
        f"/api/v1/passports/groups/{group_id}/summary"
    )

    assert response.status_code == 200
    assert response.json()["group_id"] == str(group_id)
    use_case.execute_one.assert_awaited_once()
    assert use_case.execute_one.await_args.kwargs["include_archived"] is False
    use_case.execute_page.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_archived_group_summary_requires_explicit_query_flag(
    summary_client,
) -> None:
    client, use_case, group_id = summary_client

    response = await client.get(
        f"/api/v1/passports/groups/{group_id}/summary",
        params={"include_archived": "true"},
    )

    assert response.status_code == 200
    assert use_case.execute_one.await_args.kwargs["include_archived"] is True


@pytest.mark.asyncio
async def test_single_group_summary_returns_not_found_outside_the_visible_scope(
    summary_client,
) -> None:
    client, use_case, group_id = summary_client
    use_case.execute_one.return_value = None

    response = await client.get(
        f"/api/v1/passports/groups/{group_id}/summary"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Passport group not found"


class _ScalarResult:
    def scalar_one_or_none(self):  # type: ignore[no-untyped-def]
        return None


def _sql(statement) -> str:  # type: ignore[no-untyped-def]
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


@pytest.mark.asyncio
async def test_archived_submissions_view_keeps_staff_scope_and_excludes_deleted() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    staff = _user(agency_id, role=UserRole.AGENCY_STAFF)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult())
    )
    use_case = SimpleNamespace(execute=AsyncMock(return_value=[]))

    response = await passports.list_passports_by_group_view(
        group_id=group_id,
        submission_filter="all",
        sort_by="name",
        sort_order="asc",
        page=1,
        page_size=50,
        search=None,
        include_deleted=False,
        include_archived=True,
        current_user=staff,
        session=session,
        use_case=use_case,
    )

    assert response.items == []
    call = use_case.execute.await_args.kwargs
    assert call["created_by_user_id"] == staff.id
    assert call["visible_to_user"] is staff
    assert call["include_deleted_group"] is False
    assert call["include_archived_group"] is True
    sql = _sql(session.execute.await_args.args[0])
    assert f"client_groups.id = '{group_id}'" in sql
    assert f"client_groups.agency_id = '{agency_id}'" in sql
    assert "client_groups.status != 'deleted'" in sql
    assert "client_groups.deleted_at IS NULL" in sql
    assert f"client_groups.created_by_user_id = '{staff.id}'" in sql


@pytest.mark.asyncio
async def test_submissions_view_rejects_deleted_and_archived_flags_together() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session = SimpleNamespace(execute=AsyncMock())
    use_case = SimpleNamespace(execute=AsyncMock(return_value=[]))

    with pytest.raises(HTTPException) as exc_info:
        await passports.list_passports_by_group_view(
            group_id=group_id,
            submission_filter="all",
            sort_by="name",
            sort_order="asc",
            page=1,
            page_size=50,
            search=None,
            include_deleted=True,
            include_archived=True,
            current_user=_user(agency_id, role=UserRole.SUPER_ADMIN),
            session=session,
            use_case=use_case,
        )

    assert exc_info.value.status_code == 400
    use_case.execute.assert_not_awaited()
    session.execute.assert_not_awaited()
