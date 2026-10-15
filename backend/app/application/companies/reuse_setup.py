"""Versioned operator settings, distinct from personal identity verification.

Enabling schedules historical registration and strong roster matching without
inventing traveller consent. Public document disclosure still requires proof.
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

REUSE_PURPOSE_VERSION = "company_traveller_reuse_v1"
REUSE_NOTICE_VERSION = "company_traveller_reuse_notice_v1"
REUSE_SETTING_BASIS = "operator_enabled_identity_confirmation_required"
REUSE_NOTICE_TEXT = (
    "Saved records are organized for this company. Strong matches from linked passenger lists can "
    "use suitable saved documents for the trip automatically. Travellers verify their identity "
    "before viewing saved documents and can confirm details or upload updated documents."
)


async def save_reuse_policy(
    session: AsyncSession, *, user: User, company_id: uuid.UUID, agency_id: uuid.UUID | None,
    expected_revision: int, enabled: bool, purpose_version: str | None = None,
    notice_version: str | None = None, processing_basis: str | None = None,
) -> TravellerReusePolicyModel:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    first_group = None
    if enabled:
        # Group -> company is shared with assignment and source registration.
        first_group = await session.scalar(select(ClientGroupModel).where(
            ClientGroupModel.agency_id == company.agency_id, ClientGroupModel.company_id == company.id,
            ClientGroupModel.deleted_at.is_(None), ClientGroupModel.status.in_(("active", "closed", "archived")))
            .order_by(ClientGroupModel.id).limit(1).with_for_update())
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id, lock=True)
    policy = await session.get(TravellerReusePolicyModel, company.id, populate_existing=True)
    current_revision = policy.revision if policy is not None else 0
    if expected_revision != current_revision:
        raise ConflictError("Reuse settings changed; refresh and review again")
    if enabled and company.status != "active":
        raise ConflictError("Reactivate the company before enabling historical reuse")
    if policy is None:
        policy = TravellerReusePolicyModel(company_id=company.id, agency_id=company.agency_id, revision=0)
        session.add(policy)
    policy.enabled = enabled
    # The user selected retention without automatic age purge. Withdrawal,
    # deletion and storage-authority revocation remain separate controls.
    policy.retention_mode = "until_withdrawn"
    policy.retention_days = None
    # Legacy request fields remain accepted for API compatibility. The company
    # switch records the built-in notice, never an invented legal conclusion or
    # a traveller's permission. Individual disclosure still requires proof.
    policy.purpose_version = REUSE_PURPOSE_VERSION
    policy.notice_version = REUSE_NOTICE_VERSION
    policy.processing_basis = REUSE_SETTING_BASIS
    policy.configured_at = datetime.now(UTC)
    policy.configured_by_user_id = user.id
    policy.revision = current_revision + 1
    company.revision += 1
    company.updated_at = policy.configured_at
    company.updated_by_user_id = user.id
    await session.flush()
    if enabled and first_group is not None:
        from app.application.travellers.company_history_jobs import enqueue_company_history
        await enqueue_company_history(session, group=first_group, policy=policy, trigger=f"policy:{policy.revision}")
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
