"""Live company/group/person checks for every returning-claim operation.

Indexed primary-key lookups; O(log n) database seeks and O(1) application memory.
No process cache is allowed for identity authorization or accepted revisions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.document_selection import (
    current_document_id,
    latest_document_id,
    require_frozen_selection_proof,
)
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.retained_authority import retained_authority_predicate
from app.domain.services.traveller_verification import utc
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel,
    TravellerDocumentRevisionModel,
    TravellerGroupReuseConfigModel,
    TravellerParticipationModel,
    TravellerPassportModel,
    TravellerProfileModel,
    TravellerReusePolicyModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


@dataclass(frozen=True, slots=True)
class LinkedRosterConfig:
    """Company switch applies to a linked roster without per-group setup."""

    roster_mode: Literal["closed"] = "closed"
    individual_identifier_type: str = "company_individual_code"
    identifier_required: bool = False


@dataclass(frozen=True, slots=True)
class ReuseScope:
    group: ClientGroupModel
    company: ClientOrganizationModel
    policy: TravellerReusePolicyModel
    config: TravellerGroupReuseConfigModel | LinkedRosterConfig


async def active_scope(
    session: AsyncSession, *, group_id: uuid.UUID | None = None,
    group_token: str | None = None,
) -> ReuseScope:
    predicate = ClientGroupModel.id == group_id if group_id is not None else ClientGroupModel.token == group_token
    # Explicit order is shared with assignment, enrollment and group setup.
    # A joined FOR SHARE across all tables leaves row acquisition to the query
    # planner and can deadlock with an administrator holding the group first.
    locked_group = await session.scalar(select(ClientGroupModel.id).where(predicate).with_for_update(read=True))
    if locked_group is None:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    linked = select(ClientGroupWhatsAppBroadcastLinkModel.id).where(
        ClientGroupWhatsAppBroadcastLinkModel.client_group_id == ClientGroupModel.id,
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == ClientGroupModel.agency_id,
    ).exists()
    result = (await session.execute(
        select(ClientGroupModel, ClientOrganizationModel, TravellerReusePolicyModel, TravellerGroupReuseConfigModel, linked)
        .join(ClientOrganizationModel, (ClientOrganizationModel.id == ClientGroupModel.company_id)
              & (ClientOrganizationModel.agency_id == ClientGroupModel.agency_id))
        .join(TravellerReusePolicyModel, (TravellerReusePolicyModel.company_id == ClientGroupModel.company_id)
              & (TravellerReusePolicyModel.agency_id == ClientGroupModel.agency_id))
        .outerjoin(TravellerGroupReuseConfigModel, (TravellerGroupReuseConfigModel.group_id == ClientGroupModel.id)
              & (TravellerGroupReuseConfigModel.company_id == ClientGroupModel.company_id)
              & (TravellerGroupReuseConfigModel.agency_id == ClientGroupModel.agency_id))
        .where(predicate, ClientGroupModel.status == "active", ClientGroupModel.deleted_at.is_(None),
               ClientGroupModel.import_only.is_(False), ClientOrganizationModel.status == "active",
               TravellerReusePolicyModel.enabled.is_(True))
        .with_for_update(read=True, of=ClientOrganizationModel)
        .execution_options(populate_existing=True)
    )).one_or_none()
    if result is None:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    group, company, policy, config, has_roster = result
    if has_roster:
        identifier_type = config.individual_identifier_type if config is not None else None
        return ReuseScope(group, company, policy, LinkedRosterConfig(
            individual_identifier_type=identifier_type or "company_individual_code"))
    if config is None:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    # Existing explicit no-broadcast configurations keep their prior behavior.
    # Expanding eligibility on other links requires the outstanding user decision.
    return ReuseScope(group, company, policy, config)


def check_claim_scope(claim: TravellerClaimModel, scope: ReuseScope, now: datetime) -> None:
    if utc(claim.expires_at) <= now or claim.revoked_at is not None or claim.status in {"revoked", "locked", "consumed"}:
        raise ReuseError(ReuseReason.EXPIRED)
    if (
        claim.agency_id != scope.group.agency_id or claim.company_id != scope.company.id
        or claim.expected_company_revision != scope.company.revision
        or claim.expected_group_revision != scope.group.company_revision
        or claim.expected_policy_revision != scope.policy.revision
    ):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)


async def eligible_person(
    session: AsyncSession, scope: ReuseScope, traveller_id: uuid.UUID, now: datetime,
) -> TravellerProfileModel:
    profile = await session.scalar(
        select(TravellerProfileModel).where(
            TravellerProfileModel.id == traveller_id,
            TravellerProfileModel.agency_id == scope.group.agency_id,
            TravellerProfileModel.company_id == scope.company.id,
            retained_authority_predicate(),
        ).with_for_update().execution_options(populate_existing=True)
    )
    if profile is None or (profile.retention_until is not None and utc(profile.retention_until) <= now):
        raise ReuseError(ReuseReason.UNAVAILABLE)
    if not profile.reuse_permission_evidence:
        raise ReuseError(ReuseReason.INSUFFICIENT_EVIDENCE)
    if scope.config.roster_mode == "closed":
        membership = await session.scalar(select(TravellerParticipationModel.id).where(
            TravellerParticipationModel.agency_id == scope.group.agency_id,
            TravellerParticipationModel.company_id == scope.company.id,
            TravellerParticipationModel.group_id == scope.group.id,
            TravellerParticipationModel.traveller_id == profile.id,
            TravellerParticipationModel.status != "withdrawn",
        ).limit(1))
        if membership is None:
            raise ReuseError(ReuseReason.UNAVAILABLE)
    return profile


async def accepted_document(
    session: AsyncSession, *, agency_id: uuid.UUID, company_id: uuid.UUID,
    traveller_id: uuid.UUID, passport_id: uuid.UUID,
    crypto: TravellerReuseCrypto | None = None,
) -> tuple[TravellerPassportModel, TravellerDocumentRevisionModel]:
    row = (await session.execute(select(TravellerPassportModel, TravellerDocumentRevisionModel,
        latest_document_id(TravellerPassportModel))
        .join(TravellerDocumentRevisionModel, (TravellerDocumentRevisionModel.passport_id == TravellerPassportModel.id)
              & (TravellerDocumentRevisionModel.traveller_id == TravellerPassportModel.traveller_id)
              & (TravellerDocumentRevisionModel.agency_id == TravellerPassportModel.agency_id)
              & (TravellerDocumentRevisionModel.company_id == TravellerPassportModel.company_id))
        .where(TravellerPassportModel.id == passport_id, TravellerPassportModel.agency_id == agency_id,
               TravellerPassportModel.company_id == company_id, TravellerPassportModel.traveller_id == traveller_id,
               TravellerPassportModel.status.in_(("accepted", "superseded")),
               TravellerDocumentRevisionModel.id == current_document_id(TravellerPassportModel)).limit(1)
    )).one_or_none()
    if row is None:
        raise ReuseError(ReuseReason.UNAVAILABLE)
    if row[2] != row[1].id:
        await require_frozen_selection_proof(session, row[0], row[1], crypto)
    return row[0], row[1]


def check_person_revision(claim: TravellerClaimModel, person: TravellerProfileModel) -> None:
    if (
        claim.expected_profile_revision != person.revision
        or claim.expected_contact_revision != person.contact_revision
        or claim.expected_authorization_version != person.authorization_version
    ):
        raise ReuseError(ReuseReason.REVISION_CONFLICT)
