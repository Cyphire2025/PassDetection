"""Current tenant/user/connection/lease-token claim lookup; transport owns timing policy."""

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import UserRole
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.infrastructure.database.models import UserModel
from app.infrastructure.email.ai_claim import EmailAiClaim


async def _load_valid_claim(
    session: AsyncSession,
    claim: EmailAiClaim,
    *,
    for_update: bool,
    office_roles: set[str],
    settled_statuses: set[str],
) -> (
    tuple[
        EmailAiAnalysisModel,
        EmailMessageModel,
        EmailConnectionModel,
    ]
    | None
):
    statement = (
        select(EmailAiAnalysisModel, EmailMessageModel, EmailConnectionModel)
        .join(
            EmailMessageModel,
            and_(
                EmailMessageModel.id == EmailAiAnalysisModel.message_id,
                EmailMessageModel.connection_id == EmailAiAnalysisModel.connection_id,
                EmailMessageModel.agency_id == EmailAiAnalysisModel.agency_id,
                EmailMessageModel.owner_user_id == EmailAiAnalysisModel.owner_user_id,
            ),
        )
        .join(
            EmailConnectionModel,
            and_(
                EmailConnectionModel.id == EmailAiAnalysisModel.connection_id,
                EmailConnectionModel.agency_id == EmailAiAnalysisModel.agency_id,
                EmailConnectionModel.owner_user_id == EmailAiAnalysisModel.owner_user_id,
            ),
        )
        .join(UserModel, UserModel.id == EmailAiAnalysisModel.owner_user_id)
        .where(
            EmailAiAnalysisModel.id == claim.analysis_id,
            EmailAiAnalysisModel.agency_id == claim.agency_id,
            EmailAiAnalysisModel.owner_user_id == claim.owner_user_id,
            EmailAiAnalysisModel.connection_id == claim.connection_id,
            EmailAiAnalysisModel.message_id == claim.message_id,
            EmailAiAnalysisModel.status == "processing",
            EmailAiAnalysisModel.lease_token == claim.lease_token,
            EmailConnectionModel.provider_account_id == claim.provider_account_id,
            EmailConnectionModel.sync_generation == claim.sync_generation,
            EmailConnectionModel.ai_processing_enabled.is_(True),
            EmailConnectionModel.ai_enabled_at.is_not(None),
            EmailMessageModel.received_at >= EmailConnectionModel.ai_enabled_at,
            EmailMessageModel.processing_status.in_(settled_statuses),
            EmailMessageModel.relevance_status != "failed",
            EmailMessageModel.evidence_json["human_marked_unrelated"].as_boolean().is_not(True),
            UserModel.is_active.is_(True),
            UserModel.role.in_(office_roles),
            or_(
                UserModel.role == UserRole.SUPER_ADMIN.value,
                UserModel.agency_id == EmailAiAnalysisModel.agency_id,
            ),
        )
    )
    if for_update:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.tuples().one_or_none()
