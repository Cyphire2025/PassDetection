from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import AgencyModel, ClientGroupModel, UserModel
from app.presentation.api.v1.routes.admin import get_group_passport_retention, router


def _agency_admin(*, user_id: uuid.UUID, agency_id: uuid.UUID) -> User:
    return User(
        id=user_id,
        email="retention-admin@example.com",
        hashed_password="unused",
        full_name="Retention Admin",
        role=UserRole.AGENCY_ADMIN,
        agency_id=agency_id,
    )


@pytest.mark.asyncio
async def test_retention_schedule_is_tenant_scoped_without_exposing_retired_holds(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    agency_id, user_id, group_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    group = ClientGroupModel(
        id=group_id,
        name="Archived group with legacy hold metadata",
        token=f"retention-{uuid.uuid4()}",
        agency_id=agency_id,
        status="archived",
        created_by_user_id=user_id,
        closed_at=now - timedelta(days=1),
        passport_purge_at=now + timedelta(days=364),
        passport_retention_days_applied=365,
        passport_legal_hold=True,
        passport_legal_hold_reason="Historical hold reason",
        passport_legal_hold_set_at=now - timedelta(days=2),
        passport_legal_hold_set_by_user_id=user_id,
    )
    db_session.add_all([
        AgencyModel(id=agency_id, name="Retention Agency", email=f"{agency_id}@example.com"),
        UserModel(
            id=user_id, email="retention-admin@example.com", hashed_password="hash",
            full_name="Retention Admin", role=UserRole.AGENCY_ADMIN.value,
            agency_id=agency_id,
        ),
        group,
    ])
    await db_session.flush()

    inspected = await get_group_passport_retention(
        group_id=group_id,
        current_user=_agency_admin(user_id=user_id, agency_id=agency_id),
        session=db_session,
    )
    assert inspected.model_dump() == {
        "group_id": group_id,
        "passport_purge_at": group.passport_purge_at,
        "passport_retention_days_applied": 365,
    }
    assert group.passport_legal_hold is True  # Historical records are not rewritten.

    with pytest.raises(HTTPException) as exc_info:
        await get_group_passport_retention(
            group_id=group_id,
            current_user=_agency_admin(user_id=uuid.uuid4(), agency_id=uuid.uuid4()),
            session=db_session,
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("legal_hold", [True, False])
async def test_retired_hold_mutation_endpoint_is_unavailable(legal_hold: bool) -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        response = await client.put(
            f"/api/v1/admin/groups/{uuid.uuid4()}/passport-retention",
            json={"legal_hold": legal_hold, "reason": "Old client request"},
        )
    assert response.status_code == 405
