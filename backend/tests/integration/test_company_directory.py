"""Real database constraints, tenant isolation and lifecycle-safe ownership."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import company_agency_scope, require_company
from app.application.companies.assignment import assign_group_company
from app.application.companies.directory import (
    create_company,
    delete_company,
    search_companies,
    update_company,
)
from app.application.companies.reassignment import ReassignmentReview, reassignment_preview
from app.application.dtos.client_group_dtos import CreateClientGroupInputDTO
from app.application.use_cases.client_groups.create_client_group_use_case import (
    CreateClientGroupUseCase,
)
from app.core.config.settings import Settings
from app.domain.entities.entities import ClientGroup, GroupStatus, User, UserRole
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    ConflictError,
    EntityNotFoundError,
    ValidationError,
)
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel, GCGroupAccessModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel,
    TravellerParticipationModel,
    TravellerProfileModel,
    TravellerReconciliationJobModel,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.routes.companies import company_groups, company_summary


async def seed_user(session: AsyncSession, role: UserRole = UserRole.AGENCY_ADMIN) -> User:
    key = uuid.uuid4()
    user = User.create(email=f"{key}@company.test", hashed_password="hash", full_name="Admin",
                       role=role, agency_id=uuid.uuid4())
    session.add(AgencyModel(id=user.agency_id, name="Agency", email=f"{key}@agency.test"))
    await session.flush()
    session.add(UserModel(id=user.id, email=user.email, hashed_password="hash", full_name=user.full_name,
                          role=role.value, agency_id=user.agency_id))
    await session.flush()
    return user


async def company(session: AsyncSession, user: User, name: str = "Example Client") -> ClientOrganizationModel:
    return await create_company(session, user=user, agency_id=None, name=name)


async def legacy_group(session: AsyncSession, user: User, status: GroupStatus = GroupStatus.ACTIVE) -> ClientGroup:
    group = ClientGroup.create(name="Trip", token=uuid.uuid4().hex, agency_id=user.agency_id,
                                created_by_user_id=user.id, initial_status=status)
    await ClientGroupRepository(session).save(group)
    return group


@pytest.mark.asyncio
async def test_duplicate_name_is_tenant_scoped_and_database_enforced(db_session: AsyncSession) -> None:
    user, other = await seed_user(db_session), await seed_user(db_session)
    first = await company(db_session, user, "  ACME    Travel  ")
    with pytest.raises(ConflictError):
        await company(db_session, user, "acme travel")
    assert (await company(db_session, other, "ACME Travel")).id != first.id
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(ClientOrganizationModel(agency_id=user.agency_id, name="ACME TRAVEL",
                                                    normalized_name="acme travel"))
            await db_session.flush()


@pytest.mark.asyncio
async def test_rename_status_and_revision_preserve_id(db_session: AsyncSession) -> None:
    user = await seed_user(db_session)
    original = await company(db_session, user)
    updated = await update_company(db_session, user=user, company_id=original.id, agency_id=None,
                                   expected_revision=1, changes={"name": "Renamed", "status": "inactive"})
    assert updated.id == original.id and updated.status == "inactive" and updated.revision == 2
    with pytest.raises(ConflictError):
        await update_company(db_session, user=user, company_id=original.id, agency_id=None,
                             expected_revision=1, changes={"status": "active"})
    await update_company(db_session, user=user, company_id=original.id, agency_id=None,
                         expected_revision=2, changes={"status": "active"})
    assert updated.revision == 3


@pytest.mark.asyncio
async def test_staff_lookup_does_not_grant_company_history(db_session: AsyncSession) -> None:
    user = await seed_user(db_session)
    item = await company(db_session, user)
    staff = replace(user, role=UserRole.AGENCY_STAFF)
    rows, _, _ = await search_companies(db_session, user=staff, agency_id=user.agency_id,
                                        search="", status="active", cursor=None, page_size=10, secret="test")
    assert [row.id for row in rows] == [item.id]
    with pytest.raises(AuthorizationError):
        await require_company(db_session, user=staff, company_id=item.id)
    other = await seed_user(db_session)
    with pytest.raises(EntityNotFoundError):
        await require_company(db_session, user=other, company_id=item.id)
    with pytest.raises(ValidationError):
        company_agency_scope(replace(user, role=UserRole.SUPER_ADMIN))


@pytest.mark.asyncio
async def test_directory_keyset_beyond_legacy_cap_and_cursor_bound_to_scope(db_session: AsyncSession) -> None:
    user = await seed_user(db_session)
    for index in range(205):
        db_session.add(ClientOrganizationModel(agency_id=user.agency_id, name=f"Client {index:03}",
                                                normalized_name=f"client {index:03}"))
    await db_session.flush()
    ids: list[uuid.UUID] = []
    cursor = None
    first_cursor = None
    while True:
        rows, cursor, more = await search_companies(db_session, user=user, agency_id=user.agency_id,
                                                    search="Client", status="active", cursor=cursor,
                                                    page_size=37, secret="test")
        assert len(rows) <= 37
        ids.extend(row.id for row in rows)
        first_cursor = first_cursor or cursor
        if not more:
            break
    assert len(ids) == len(set(ids)) == 205
    with pytest.raises(ValidationError):
        await search_companies(db_session, user=user, agency_id=user.agency_id, search="changed",
                               status="active", cursor=first_cursor, page_size=37, secret="test")


@pytest.mark.asyncio
@pytest.mark.parametrize("import_only", [False, True])
async def test_creation_requires_active_same_tenant_company(db_session: AsyncSession, import_only: bool) -> None:
    user, other = await seed_user(db_session), await seed_user(db_session)
    item, foreign = await company(db_session, user), await company(db_session, other)
    use_case = CreateClientGroupUseCase(ClientGroupRepository(db_session))
    for identifier in (None, foreign.id):
        with pytest.raises(ValidationError):
            await use_case.execute(CreateClientGroupInputDTO(name="Trip", company_id=identifier, import_only=import_only),
                                    agency_id=user.agency_id, created_by_user_id=user.id)
    dto = await use_case.execute(CreateClientGroupInputDTO(name="Trip", company_id=item.id, import_only=import_only),
                                 agency_id=user.agency_id, created_by_user_id=user.id)
    assert dto.company_id == item.id and dto.company_revision == 1
    assert dto.company == {"id": item.id, "name": item.name, "status": "active"}
    await update_company(db_session, user=user, company_id=item.id, agency_id=None,
                         expected_revision=1, changes={"status": "inactive"})
    with pytest.raises(ValidationError):
        await use_case.execute(CreateClientGroupInputDTO(name="Trip", company_id=item.id),
                                agency_id=user.agency_id, created_by_user_id=user.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [GroupStatus.CLOSED, GroupStatus.ARCHIVED])
async def test_company_only_assignment_preserves_closed_archived_state(db_session: AsyncSession, status: GroupStatus) -> None:
    user = await seed_user(db_session)
    item, group = await company(db_session, user), await legacy_group(db_session, user, status)
    before = (group.status.value, group.token, group.closed_at.replace(tzinfo=None) if group.closed_at else None, group.passport_purge_at)
    assigned = await assign_group_company(db_session, user=user, agency_id=user.agency_id, group_id=group.id,
                                          company_id=item.id, expected_revision=0)
    assert (assigned.status, assigned.token, assigned.closed_at.replace(tzinfo=None) if assigned.closed_at else None, assigned.passport_purge_at) == before
    assert assigned.company_id == item.id and assigned.company_revision == 1
    assert await db_session.scalar(select(GCGroupAccessModel.id).where(GCGroupAccessModel.group_id == group.id)) is None
    with pytest.raises(ConflictError):
        await delete_company(db_session, user=user, company_id=item.id, agency_id=None, expected_revision=1)


@pytest.mark.asyncio
async def test_populated_reassignment_blocked_and_legacy_update_preserves_assignment(db_session: AsyncSession) -> None:
    user = await seed_user(db_session)
    first, second = await company(db_session, user), await company(db_session, user, "Another")
    group = await legacy_group(db_session, user)
    await assign_group_company(db_session, user=user, agency_id=user.agency_id, group_id=group.id,
                               company_id=first.id, expected_revision=0)
    db_session.add(PassportSubmissionModel(group_id=group.id, agency_id=user.agency_id,
                                           client_name="Passenger", image_s3_key="test.png"))
    await db_session.flush()
    with pytest.raises(ConflictError, match="reconciliation"):
        await assign_group_company(db_session, user=user, agency_id=user.agency_id, group_id=group.id,
                                   company_id=second.id, expected_revision=1)
    group.name = "Unrelated edit using stale entity"
    await ClientGroupRepository(db_session).update(group)
    saved = await ClientGroupRepository(db_session).get_by_id(group.id)
    assert saved.company_id == first.id


@pytest.mark.asyncio
async def test_summary_exact_lifecycles_exclude_deleted(db_session: AsyncSession, test_settings: Settings) -> None:
    user = await seed_user(db_session)
    item = await company(db_session, user)
    for status in (GroupStatus.ACTIVE, GroupStatus.CLOSED, GroupStatus.ARCHIVED, GroupStatus.DELETED):
        group = await legacy_group(db_session, user, status)
        row = await db_session.get(ClientGroupModel, group.id)
        row.company_id = item.id
    await db_session.flush()
    summary = await company_summary(item.id, agency_id=None, user=user, session=db_session)
    assert (summary.active_groups, summary.closed_groups, summary.archived_groups, summary.total_groups) == (1, 1, 1, 3)
    page = await company_groups(item.id, search="", status="all", import_only=None, cursor=None, page_size=100,
                                agency_id=None, user=user, session=db_session, settings=test_settings)
    assert len(page.items) == 3
    assert summary.unique_travellers == summary.trip_participations == 0
    assert not summary.identity_totals_partial


@pytest.mark.asyncio
async def test_database_rejects_cross_tenant_company_reference(db_session: AsyncSession) -> None:
    user, other = await seed_user(db_session), await seed_user(db_session)
    item = await company(db_session, other)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(ClientGroupModel(name="Illegal", agency_id=user.agency_id, token=uuid.uuid4().hex,
                                            created_by_user_id=user.id, company_id=item.id))
            await db_session.flush()


@pytest.mark.asyncio
async def test_reviewed_reassignment_preserves_frozen_history_and_revokes_claim(db_session: AsyncSession) -> None:
    user = await seed_user(db_session)
    source, target = await company(db_session, user), await company(db_session, user, "Target")
    group = await legacy_group(db_session, user, GroupStatus.CLOSED)
    await assign_group_company(db_session, user=user, agency_id=user.agency_id, group_id=group.id,
                               company_id=source.id, expected_revision=0)
    profile = TravellerProfileModel(id=uuid.uuid4(), agency_id=user.agency_id, company_id=source.id, status="active")
    db_session.add(profile)
    await db_session.flush()
    source_record = PassportSubmissionModel(id=uuid.uuid4(), group_id=group.id, agency_id=user.agency_id,
                                             client_name="Historical Person", image_s3_key="existing-source.png")
    db_session.add(source_record)
    await db_session.flush()
    participation = TravellerParticipationModel(
        agency_id=user.agency_id, company_id=source.id, group_id=group.id, traveller_id=profile.id,
        source_submission_id=source_record.id, source_kind="accepted_submission", source_row_key=str(source_record.id),
        profile_revision=1, contact_revision=1, question_version="historical-v1", status="accepted",
        idempotency_key="historical-participation",
    )
    claim = TravellerClaimModel(
        agency_id=user.agency_id, company_id=source.id, group_id=group.id, method="phone", max_attempts=5,
        secret_hash="a" * 64, expires_at=datetime.now(UTC) + timedelta(minutes=10), idempotency_key="live-claim",
    )
    db_session.add_all([participation, claim])
    await db_session.flush()
    preview = await reassignment_preview(db_session, user=user, agency_id=user.agency_id,
                                         group_id=group.id, company_id=target.id)
    assert preview["accepted_participations"] == preview["submission_records"] == preview["active_claims"] == 1
    assert preview["can_reassign"]
    with pytest.raises(ConflictError, match="records changed"):
        await assign_group_company(db_session, user=user, agency_id=user.agency_id, group_id=group.id,
                                   company_id=target.id, expected_revision=1,
                                   review=ReassignmentReview(99, "Correct company ownership"))
    assigned = await assign_group_company(db_session, user=user, agency_id=user.agency_id, group_id=group.id,
                                           company_id=target.id, expected_revision=1,
                                           review=ReassignmentReview(preview["expected_roster_revision"], "Correct company ownership"))
    await db_session.flush()
    assert assigned.status == "closed" and assigned.company_id == target.id and assigned.company_revision == 2
    assert profile.company_id == participation.company_id == source.id
    await db_session.refresh(claim)
    assert claim.status == "revoked" and claim.revoked_at is not None
    job = await db_session.scalar(select(TravellerReconciliationJobModel).where(
        TravellerReconciliationJobModel.group_id == group.id, TravellerReconciliationJobModel.status == "queued",
    ))
    assert job.company_id == target.id and job.expected_group_revision == 2
    assert source_record.group_id == group.id
    with pytest.raises(ConflictError, match="assignment changed"):
        await assign_group_company(db_session, user=user, agency_id=user.agency_id, group_id=group.id,
                                   company_id=source.id, expected_revision=1,
                                   review=ReassignmentReview(0, "Outdated change request"))


@pytest.mark.asyncio
async def test_unused_inactive_delete_and_profile_dependency(db_session: AsyncSession) -> None:
    user = await seed_user(db_session)
    unused = await company(db_session, user)
    await update_company(db_session, user=user, company_id=unused.id, agency_id=None,
                         expected_revision=1, changes={"status": "inactive"})
    await delete_company(db_session, user=user, company_id=unused.id, agency_id=None, expected_revision=2)
    assert unused.status == "deleted" and unused.deleted_at is not None
    fresh = await company(db_session, user)
    assert fresh.id != unused.id
    db_session.add(TravellerProfileModel(agency_id=user.agency_id, company_id=fresh.id))
    await db_session.flush()
    with pytest.raises(ConflictError, match="history"):
        await delete_company(db_session, user=user, company_id=fresh.id, agency_id=None, expected_revision=1)
