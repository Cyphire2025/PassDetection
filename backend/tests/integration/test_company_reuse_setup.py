"""Explicit purpose, tenant constraints and irreversible authority generations."""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.assignment import assign_group_company
from app.application.companies.reuse_setup import save_group_reuse_config, save_reuse_policy
from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    ConflictError,
    EntityNotFoundError,
    ValidationError,
)
from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel
from tests.integration.test_company_directory import company, legacy_group, seed_user


async def enable_policy(session, user, item, **overrides):
    values = dict(expected_revision=0, enabled=True, purpose_version="corporate-trips-v1",
                  notice_version="traveller-notice-v1", processing_basis="documented-consent-reference")
    return await save_reuse_policy(session, user=user, company_id=item.id, agency_id=None, **{**values, **overrides})


@pytest.mark.asyncio
async def test_policy_requires_explicit_basis_without_promoting_legacy_permission(db_session: AsyncSession) -> None:
    user = await seed_user(db_session)
    item = await company(db_session, user)
    profile = TravellerProfileModel(agency_id=user.agency_id, company_id=item.id)
    db_session.add(profile)
    await db_session.flush()
    with pytest.raises(ValidationError):
        await enable_policy(db_session, user, item, processing_basis=None)
    policy = await enable_policy(db_session, user, item)
    assert policy.enabled and policy.retention_mode == "until_withdrawn" and policy.retention_days is None
    assert profile.reuse_permission_status == "unknown"
    assert item.revision == 2
    with pytest.raises(ConflictError):
        await enable_policy(db_session, user, item)
    await enable_policy(db_session, user, item, expected_revision=1, enabled=False)
    await enable_policy(db_session, user, item, expected_revision=2, enabled=True)
    assert policy.revision == 3 and item.revision == 4


@pytest.mark.asyncio
async def test_setup_denies_staff_cross_tenant_and_inactive_company(db_session: AsyncSession) -> None:
    user, other = await seed_user(db_session), await seed_user(db_session)
    item = await company(db_session, user)
    with pytest.raises(AuthorizationError):
        await enable_policy(db_session, replace(user, role=UserRole.AGENCY_STAFF), item)
    with pytest.raises(EntityNotFoundError):
        await enable_policy(db_session, other, item)
    item.status = "inactive"
    await db_session.flush()
    with pytest.raises(ConflictError):
        await enable_policy(db_session, user, item)


@pytest.mark.asyncio
async def test_group_config_disable_reenable_never_revives_old_generation(db_session: AsyncSession) -> None:
    user = await seed_user(db_session)
    item, group = await company(db_session, user), await legacy_group(db_session, user)
    await assign_group_company(db_session, user=user, agency_id=user.agency_id, group_id=group.id,
                               company_id=item.id, expected_revision=0)
    args = dict(session=db_session, user=user, company_id=item.id, agency_id=None, group_id=group.id,
                roster_mode="closed", individual_identifier_type="employee_id", identifier_required=True)
    model, config = await save_group_reuse_config(**args, expected_revision=0, expected_group_revision=1, enabled=True)
    assert config.revision == 1 and model.company_revision == 2
    with pytest.raises(ConflictError):
        await save_group_reuse_config(**args, expected_revision=1, expected_group_revision=1, enabled=False)
    model, config = await save_group_reuse_config(**args, expected_revision=1, expected_group_revision=2, enabled=False)
    assert config is None and model.company_revision == 3
    model, config = await save_group_reuse_config(**args, expected_revision=0, expected_group_revision=3, enabled=True)
    assert config.revision == 1 and model.company_revision == 4


@pytest.mark.asyncio
async def test_required_code_needs_stable_individual_meaning(db_session: AsyncSession) -> None:
    user = await seed_user(db_session)
    item, group = await company(db_session, user), await legacy_group(db_session, user)
    await assign_group_company(db_session, user=user, agency_id=user.agency_id, group_id=group.id,
                               company_id=item.id, expected_revision=0)
    with pytest.raises(ValidationError):
        await save_group_reuse_config(db_session, user=user, company_id=item.id, agency_id=None, group_id=group.id,
                                       expected_revision=0, expected_group_revision=1, enabled=True, roster_mode="open",
                                       individual_identifier_type=None, identifier_required=True)
