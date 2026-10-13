"""Explicit company purpose and per-group eligibility configuration.

No legacy submission receives permission by enabling these settings. Each
profile still requires its own documented permission before historical reuse.
Company and group generations advance on configuration changes, so disabling
then re-enabling a setting never revives a previously issued proof.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import require_company
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import ConflictError, EntityNotFoundError, ValidationError
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerGroupReuseConfigModel,
    TravellerReusePolicyModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


async def save_reuse_policy(
    session: AsyncSession, *, user: User, company_id: uuid.UUID, agency_id: uuid.UUID | None,
    expected_revision: int, enabled: bool, purpose_version: str | None,
    notice_version: str | None, processing_basis: str | None,
) -> TravellerReusePolicyModel:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id, lock=True)
    policy = await session.get(TravellerReusePolicyModel, company.id, populate_existing=True)
    current_revision = policy.revision if policy is not None else 0
    if expected_revision != current_revision:
        raise ConflictError("Reuse settings changed; refresh and review again")
    if enabled and company.status != "active":
        raise ConflictError("Reactivate the company before enabling historical reuse")
    if enabled and not all(value and value.strip() for value in (purpose_version, notice_version, processing_basis)):
        raise ValidationError("Enabling reuse requires the documented purpose, notice and processing basis")
    if policy is None:
        policy = TravellerReusePolicyModel(company_id=company.id, agency_id=company.agency_id, revision=0)
        session.add(policy)
    policy.enabled = enabled
    # The user selected retention without automatic age purge. Withdrawal,
    # deletion and storage-authority revocation remain separate controls.
    policy.retention_mode = "until_withdrawn"
    policy.retention_days = None
    policy.purpose_version = purpose_version.strip() if purpose_version else None
    policy.notice_version = notice_version.strip() if notice_version else None
    policy.processing_basis = processing_basis.strip() if processing_basis else None
    policy.configured_at = datetime.now(UTC)
    policy.configured_by_user_id = user.id
    policy.revision = current_revision + 1
    company.revision += 1
    company.updated_at = policy.configured_at
    company.updated_by_user_id = user.id
    await session.flush()
    await AuditLogRepository(session).record(
        action="company.reuse_policy_configured", entity_type="client_organization", entity_id=str(company.id),
        agency_id=company.agency_id, user_id=user.id, actor_email=user.email,
        metadata={"enabled": enabled, "revision": policy.revision, "retention_mode": "until_withdrawn",
                  "purpose_version": policy.purpose_version, "notice_version": policy.notice_version},
    )
    return policy


async def require_company_group(
    session: AsyncSession, *, user: User, company_id: uuid.UUID, agency_id: uuid.UUID | None,
    group_id: uuid.UUID, lock: bool = False,
) -> ClientGroupModel:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    query = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id, ClientGroupModel.agency_id == company.agency_id,
        ClientGroupModel.company_id == company.id, ClientGroupModel.status != "deleted",
        ClientGroupModel.deleted_at.is_(None),
    )
    if lock:
        query = query.with_for_update(of=ClientGroupModel).execution_options(populate_existing=True)
    group = await session.scalar(query)
    if group is None:
        raise EntityNotFoundError("ClientGroup", group_id)
    await AuthorizationPolicy(session).require_manage_group(user, group)
    return group


async def save_group_reuse_config(
    session: AsyncSession, *, user: User, company_id: uuid.UUID, agency_id: uuid.UUID | None,
    group_id: uuid.UUID, expected_revision: int, expected_group_revision: int, enabled: bool,
    roster_mode: str, individual_identifier_type: str | None, identifier_required: bool,
) -> tuple[ClientGroupModel, TravellerGroupReuseConfigModel | None]:
    group = await require_company_group(session, user=user, company_id=company_id, agency_id=agency_id,
                                         group_id=group_id, lock=True)
    config = await session.get(TravellerGroupReuseConfigModel, group.id, populate_existing=True)
    if group.company_revision != expected_group_revision or (config.revision if config else 0) != expected_revision:
        raise ConflictError("Group reuse settings changed; refresh and review again")
    if roster_mode not in ("closed", "open"):
        raise ValidationError("Choose a closed roster or an explicitly open collection group")
    if identifier_required and not individual_identifier_type:
        raise ValidationError("An individual identifier type is required for this code policy")
    company = await require_company(session, user=user, company_id=company_id, agency_id=group.agency_id, lock=True)
    if enabled and company.status != "active":
        raise ConflictError("Reactivate the company before enabling historical reuse")
    previous_revision = config.revision if config else 0
    if not enabled:
        if config is not None:
            await session.delete(config)
        config = None
    else:
        if config is None:
            config = TravellerGroupReuseConfigModel(group_id=group.id, agency_id=group.agency_id,
                                                     company_id=company.id, revision=0)
            session.add(config)
        config.company_id = company.id
        config.roster_mode = roster_mode
        config.individual_identifier_type = individual_identifier_type
        config.identifier_required = identifier_required
        config.revision = previous_revision + 1
    group.company_revision += 1
    await session.flush()
    await AuditLogRepository(session).record(
        action="company.group_reuse_configured", entity_type="client_group", entity_id=str(group.id),
        agency_id=group.agency_id, user_id=user.id, actor_email=user.email,
        metadata={"enabled": enabled, "company_id": str(company.id), "group_revision": group.company_revision,
                  "roster_mode": roster_mode, "individual_identifier_type": individual_identifier_type,
                  "identifier_required": identifier_required},
    )
    return group, config
