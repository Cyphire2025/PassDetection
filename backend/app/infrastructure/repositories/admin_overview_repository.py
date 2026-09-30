"""The seven existing website counts, with no business entity hydration."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.application.use_cases.admin_overview import AdminOverviewCounts
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    PENDING_REVIEW_PASSPORT_STATUS_VALUES,
    PassportProcessingStatus,
    UserRole,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)


class AdminOverviewRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def overview(self, *, role: UserRole, agency_id: uuid.UUID | None) -> AdminOverviewCounts:
        # Authorization stays with each transport. Preserve the website's exact
        # agency predicates, including IS NULL for a non-Superadmin without one.
        agency_filter = [] if role == UserRole.SUPER_ADMIN else [AgencyModel.id == agency_id]
        user_filter = [] if role == UserRole.SUPER_ADMIN else [UserModel.agency_id == agency_id]
        group_filter = [] if role == UserRole.SUPER_ADMIN else [ClientGroupModel.agency_id == agency_id]
        passport_filter = [] if role == UserRole.SUPER_ADMIN else [PassportSubmissionModel.agency_id == agency_id]
        visible = PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES)
        active_parent = ClientGroupModel.status.notin_(["archived", "deleted"])

        async def count(query: Select[tuple[int]]) -> int:
            return int((await self.session.execute(query)).scalar_one())

        passport_query = select(func.count()).select_from(PassportSubmissionModel)
        joined = passport_query.join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        return AdminOverviewCounts(
            agencies=await count(select(func.count()).select_from(AgencyModel).where(*agency_filter)),
            users=await count(select(func.count()).select_from(UserModel).where(*user_filter)),
            client_groups=await count(select(func.count()).select_from(ClientGroupModel).where(*group_filter)),
            passport_submissions=await count(passport_query.where(*passport_filter, visible)),
            pending_review=await count(joined.where(*passport_filter,
                PassportSubmissionModel.status.in_(PENDING_REVIEW_PASSPORT_STATUS_VALUES), active_parent)),
            client_submitted=await count(joined.where(*passport_filter, visible, active_parent)),
            failed=await count(joined.where(*passport_filter,
                PassportSubmissionModel.status == PassportProcessingStatus.FAILED.value, active_parent)),
        )
