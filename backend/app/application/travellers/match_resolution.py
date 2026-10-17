"""Human-reviewed roster inclusion never implies ownership, submission or consent."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.match_freshness import require_fresh_match
from app.domain.exceptions.exceptions import ConflictError, EntityNotFoundError
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerMatchCaseModel,
    TravellerParticipationModel,
    TravellerProfileModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


async def resolve_match(session: AsyncSession, *, agency_id: uuid.UUID, company_id: uuid.UUID,
    group_id: uuid.UUID, case_id: uuid.UUID, traveller_id: uuid.UUID,
    expected_revision: int, expected_group_revision: int, actor_id: uuid.UUID, reason: str,
    crypto: TravellerReuseCrypto,
) -> TravellerParticipationModel:
    # Same lock order as assignment/public authority: group, company, person.
    group = await session.scalar(select(ClientGroupModel).where(
        ClientGroupModel.id == group_id, ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.company_id == company_id, ClientGroupModel.deleted_at.is_(None),
        ClientGroupModel.status.in_(("active", "closed", "archived")),
    ).with_for_update(read=True).execution_options(populate_existing=True))
    if group is None or group.company_revision != expected_group_revision:
        raise ConflictError("Group assignment changed. Refresh the matching preview.")
    company = await session.scalar(select(ClientOrganizationModel.id).where(
        ClientOrganizationModel.id == company_id, ClientOrganizationModel.agency_id == agency_id,
        ClientOrganizationModel.status == "active",
    ).with_for_update(read=True))
    if company is None:
        raise ConflictError("An active company is required to include a traveller.")
    person = await session.scalar(select(TravellerProfileModel).where(
        TravellerProfileModel.id == traveller_id, TravellerProfileModel.agency_id == agency_id,
        TravellerProfileModel.company_id == company_id, TravellerProfileModel.status == "active",
        TravellerProfileModel.deleted_at.is_(None),
    ).with_for_update().execution_options(populate_existing=True))
    if person is None:
        raise EntityNotFoundError("Traveller", traveller_id)
    case = await session.scalar(select(TravellerMatchCaseModel).where(
        TravellerMatchCaseModel.id == case_id, TravellerMatchCaseModel.agency_id == agency_id,
        TravellerMatchCaseModel.company_id == company_id, TravellerMatchCaseModel.group_id == group_id,
    ).with_for_update().execution_options(populate_existing=True))
    if case is None:
        raise EntityNotFoundError("Match case", case_id)
    if case.revision != expected_revision or case.status in {"purged", "resolved", "pending"}:
        raise ConflictError("This match changed. Refresh before recording a decision.")
    await require_fresh_match(session, case=case, group_revision=group.company_revision, crypto=crypto)
    participation = await session.scalar(select(TravellerParticipationModel).where(
        TravellerParticipationModel.agency_id == agency_id, TravellerParticipationModel.company_id == company_id,
        TravellerParticipationModel.group_id == group_id, TravellerParticipationModel.traveller_id == person.id,
    ).with_for_update())
    if participation is not None and participation.status == "withdrawn":
        raise ConflictError("This person was withdrawn. Review inclusion before resolving the match.")
    if participation is None:
        participation = TravellerParticipationModel(agency_id=agency_id, company_id=company_id, group_id=group_id,
            traveller_id=person.id, source_kind="reviewed_roster", source_row_key=f"{case.source_kind}:{case.source_row_key}",
            status="pending", profile_revision=person.revision, contact_revision=person.contact_revision,
            question_version="unanswered", confirmations={}, answers={}, idempotency_key=f"match:{case.id}")
        session.add(participation)
    case.status, case.traveller_id = "resolved", person.id
    case.revision += 1
    case.resolved_at = datetime.now(UTC)
    case.evidence = {**case.evidence, "resolution": {"actor_id": str(actor_id), "reason": reason,
        "resolved_at": case.resolved_at.isoformat(), "profile_revision": person.revision}}
    await AuditLogRepository(session).record(action="traveller.match_resolved", entity_type="traveller_match_case",
        entity_id=str(case.id), agency_id=agency_id, user_id=actor_id,
        metadata={"traveller_id": str(person.id), "group_id": str(group_id), "revision": case.revision})
    await session.flush()
    return participation
