from __future__ import annotations

import uuid
from io import BytesIO

import pytest
from fastapi import UploadFile
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.client_groups.create_client_group_use_case import (
    CreateClientGroupUseCase,
)
from app.application.use_cases.client_groups.get_client_group_by_token_use_case import (
    GetClientGroupByTokenUseCase,
)
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.models import AgencyModel, PassportSubmissionModel, UserModel
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.routes.client_groups import create_client_group
from app.presentation.api.v1.routes.passport_routes.excel_import import import_passports_by_group
from app.presentation.api.v1.schemas.client_group_schemas import CreateClientGroupRequest


@pytest.mark.asyncio
async def test_create_import_group_import_excel_and_reload_workspace(db_session: AsyncSession):
    user = User.create(
        email="import-admin@example.test", hashed_password="test-hash",
        full_name="Import Admin", role=UserRole.AGENCY_ADMIN, agency_id=uuid.uuid4(),
    )
    db_session.add_all([
        AgencyModel(id=user.agency_id, name="Import Agency", email="agency@example.test"),
        UserModel(id=user.id, email=user.email, hashed_password=user.hashed_password,
                  full_name=user.full_name, role=user.role.value, agency_id=user.agency_id),
    ])
    await db_session.flush()
    repo = ClientGroupRepository(db_session)
    response = await create_client_group(
        request=CreateClientGroupRequest(
            name="Final traveller list", destination="Dubai", travel_date="2026-11-10",
            return_date="2026-11-15", timezone="Asia/Kolkata", import_only=True,
        ),
        current_user=user, use_case=CreateClientGroupUseCase(repo), session=db_session,
    )
    await db_session.commit()
    assert response.import_only
    with pytest.raises(EntityNotFoundError):
        await GetClientGroupByTokenUseCase(repo).execute(response.token)

    workbook = Workbook()
    workbook.active.append(["Staff Name", "PASSPORT_NO"])
    workbook.active.append(["ASHA RAO", "P1234567"])
    workbook.active.append(["NIPUN KUMAR", "Z1234567"])
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    content = payload.getvalue()
    result = await import_passports_by_group(
        group_id=response.id,
        file=UploadFile(file=BytesIO(content), filename="final-list.xlsx"),
        current_user=user, session=db_session,
    )
    assert result.imported_count == 2
    summaries = await PassportSubmissionRepository(db_session).list_group_summaries_by_agency(user.agency_id)
    assert len(summaries) == 1
    assert summaries[0].import_only is True
    assert summaries[0].total_passports == 2
    assert summaries[0].group_id == response.id

    repeated = await import_passports_by_group(
        group_id=response.id,
        file=UploadFile(file=BytesIO(content), filename="final-list.xlsx"),
        current_user=user, session=db_session,
    )
    assert repeated.imported_count == 0
    assert repeated.updated_count == 2
    submissions = (await db_session.execute(select(PassportSubmissionModel).where(
        PassportSubmissionModel.group_id == response.id,
    ))).scalars().all()
    assert len(submissions) == 2
