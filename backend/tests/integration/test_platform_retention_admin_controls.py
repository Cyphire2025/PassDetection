from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    UserModel,
)
from app.presentation.api.v1.routes.admin import (
    get_group_passport_retention,
    update_group_passport_retention,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    PassportRetentionControlRequest,
)


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
async def test_retention_control_is_tenant_scoped_and_audits_hold_and_release(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    agency_id = uuid.uuid4()
    user_id = uuid.uuid4()
    group_id = uuid.uuid4()
    db_session.add_all(
        [
            AgencyModel(
                id=agency_id,
                name="Retention Controls Agency",
                email=f"{agency_id}@example.com",
            ),
            UserModel(
                id=user_id,
                email="retention-admin@example.com",
                hashed_password="hash",
                full_name="Retention Admin",
                role=UserRole.AGENCY_ADMIN.value,
                agency_id=agency_id,
            ),
            ClientGroupModel(
                id=group_id,
                name="Retention control group",
                token=f"retention-{uuid.uuid4()}",
                agency_id=agency_id,
                status="closed",
                created_by_user_id=user_id,
                created_at=now - timedelta(days=5),
                closed_at=now - timedelta(days=1),
            ),
        ]
    )
    await db_session.flush()
    current_user = _agency_admin(user_id=user_id, agency_id=agency_id)

    held = await update_group_passport_retention(
        group_id=group_id,
        body=PassportRetentionControlRequest(
            legal_hold=True,
            reason="Active passenger litigation request",
        ),
        current_user=current_user,
        session=db_session,
    )

    assert held.legal_hold is True
    assert held.legal_hold_reason == "Active passenger litigation request"
    assert held.passport_retention_days_applied == 365
    assert held.passport_purge_at is not None
    inspected = await get_group_passport_retention(
        group_id=group_id,
        current_user=current_user,
        session=db_session,
    )
    assert inspected.group_id == held.group_id
    assert inspected.legal_hold is True
    assert inspected.legal_hold_reason == held.legal_hold_reason
    assert inspected.passport_retention_days_applied == 365

    with pytest.raises(HTTPException) as exc_info:
        await get_group_passport_retention(
            group_id=group_id,
            current_user=_agency_admin(
                user_id=uuid.uuid4(),
                agency_id=uuid.uuid4(),
            ),
            session=db_session,
        )
    assert exc_info.value.status_code == 404

    released = await update_group_passport_retention(
        group_id=group_id,
        body=PassportRetentionControlRequest(
            legal_hold=False,
            reason="Legal team approved hold release",
        ),
        current_user=current_user,
        session=db_session,
    )

    assert released.legal_hold is False
    assert released.legal_hold_reason is None
    actions = list(
        (
            await db_session.execute(
                select(AuditLogModel.action)
                .where(AuditLogModel.entity_id == str(group_id))
                .order_by(AuditLogModel.created_at)
            )
        ).scalars()
    )
    assert actions == [
        "passport_legal_hold_placed",
        "passport_legal_hold_released",
    ]
