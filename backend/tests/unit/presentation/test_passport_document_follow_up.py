"""Persisted office flags: scope, atomic selection, lifecycle and read contracts."""

from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import select

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.passports.roster_view_service import prepared_roster
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.passport_routes.document_follow_up import (
    bulk_document_follow_up,
    router,
)
from app.presentation.api.v1.routes.passports import router as passports_router
from app.presentation.api.v1.schemas.passport_schemas import BulkDocumentFollowUpRequest
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf


@pytest.fixture
async def roster(db_session):
    agency_id, actor_id, group_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db_session.add(AgencyModel(id=agency_id, name="Synthetic", email=f"{agency_id}@example.test"))
    await db_session.flush()
    actor = UserModel(id=actor_id, agency_id=agency_id, role="agency_admin", full_name="Staff",
                      email=f"{actor_id}@example.test", hashed_password="unused")
    db_session.add(actor)
    await db_session.flush()
    group = ClientGroupModel(id=group_id, agency_id=agency_id, created_by_user_id=actor_id,
                             name="Synthetic group", token=uuid.uuid4().hex)
    db_session.add(group)
    await db_session.flush()
    rows = [PassportSubmissionModel(id=uuid.uuid4(), group_id=group_id, agency_id=agency_id,
        client_name=f"Passenger {index}", image_s3_key="synthetic/front.jpg", status=state,
        extraction_status="extraction_complete", extraction_revision=3,
        post_submission_verification_revision=2,
        confirmed_fields={"passport_number": f"P{index}", "given_names": f"Passenger {index}"})
        for index, state in enumerate(["ai_approved", "staff_approved", "needs_review"])]
    db_session.add_all(rows)
    await db_session.commit()
    return SimpleNamespace(session=db_session, actor=actor, user=UserRepository._to_entity(actor),
                           group=group, rows=rows)


async def save(roster, ids=None, *, flagged=True, user=None):
    return await bulk_document_follow_up(
        roster.group.id, BulkDocumentFollowUpRequest(
            submission_ids=ids if ids is not None else [row.id for row in roster.rows], flagged=flagged),
        Response(), current_user=user or roster.user, session=roster.session, _csrf=None,
    )


@pytest.mark.parametrize("role", ["agency_staff", "agency_manager", "agency_admin", "super_admin"])
async def test_flag_clear_are_persistent_audited_and_preserve_verification(roster, role):
    roster.actor.role = role
    await roster.session.commit()
    roster.user = UserRepository._to_entity(roster.actor)
    before = [(row.status, row.extraction_revision, row.post_submission_verification_revision,
               row.confirmed_fields.copy(), row.image_s3_key) for row in roster.rows]
    result = await save(roster, [roster.rows[0].id, *[row.id for row in roster.rows]])
    assert result.updated_count == 3 and result.flagged
    for row, original in zip(roster.rows, before, strict=True):
        await roster.session.refresh(row)
        assert row.document_follow_up is True
        assert (row.status, row.extraction_revision, row.post_submission_verification_revision,
                row.confirmed_fields, row.image_s3_key) == original
    assert (await save(roster)).updated_count == 0
    audit = (await roster.session.scalars(select(AuditLogModel))).all()
    assert len(audit) == 1 and audit[0].metadata_json["updated_count"] == 3
    assert audit[0].user_id == roster.user.id
    assert (await save(roster, flagged=False)).updated_count == 3
    assert not any(row.document_follow_up for row in roster.rows)


async def test_stale_repository_entity_update_cannot_clear_manual_flag(roster):
    repository = PassportSubmissionRepository(roster.session)
    stale = await repository.get_by_id(roster.rows[0].id)
    assert stale is not None and not stale.document_follow_up
    await save(roster, [stale.id])
    await repository.update(replace(stale, client_name="Corrected spelling"))
    await roster.session.commit()
    fresh = await repository.get_by_id(stale.id)
    assert fresh is not None and fresh.document_follow_up
    assert fresh.client_name == "Corrected spelling"


async def test_group_count_survives_search_status_and_pagination(roster):
    await save(roster, [roster.rows[1].id])
    for filter_value, search, expected in (("all", "Passenger 0", 1),
                                          ("ai_approved", None, 1),
                                          ("document_follow_up", None, 1),
                                          ("document_follow_up", "absent", 0)):
        prepared, _ = await prepared_roster(roster.session, group_id=roster.group.id,
            user=roster.user, include_deleted=False, submission_filter=filter_value,
            sort_by="name", sort_order="asc", search=search, page_size=1)
        assert prepared.document_follow_up_count == prepared.page(1).document_follow_up_count == 1
        assert prepared.group_total == 3 and prepared.total == expected
        if filter_value == "document_follow_up" and expected:
            assert prepared.ordered_submission_ids == (roster.rows[1].id,)
    await save(roster, flagged=False)
    prepared, _ = await prepared_roster(roster.session, group_id=roster.group.id,
        user=roster.user, include_deleted=False, submission_filter="all",
        sort_by="name", sort_order="asc", search=None, page_size=1)
    assert prepared.document_follow_up_count == 0


@pytest.mark.parametrize("invalid_kind", ["other_group", "upload", "missing"])
async def test_mixed_invalid_selection_never_partially_flags(roster, invalid_kind):
    extra_id = uuid.uuid4()
    if invalid_kind == "other_group":
        group = ClientGroupModel(id=uuid.uuid4(), agency_id=roster.group.agency_id,
                                 name="Other", token=uuid.uuid4().hex)
        roster.session.add(group)
        await roster.session.flush()
        roster.session.add(PassportSubmissionModel(id=extra_id, group_id=group.id,
            agency_id=group.agency_id, client_name="Other", status="submitted", image_s3_key="synthetic"))
    elif invalid_kind == "upload":
        roster.session.add(PassportSubmissionModel(id=extra_id, group_id=roster.group.id,
            agency_id=roster.group.agency_id, client_name="Upload", status="processing", image_s3_key="synthetic"))
    await roster.session.commit()
    with pytest.raises(HTTPException) as error:
        await save(roster, [roster.rows[0].id, extra_id])
    assert error.value.status_code == 404
    await roster.session.rollback()
    rows = (await roster.session.scalars(select(PassportSubmissionModel))).all()
    assert not any(row.document_follow_up for row in rows)
    assert not (await roster.session.scalars(select(AuditLogModel))).all()


@pytest.mark.parametrize("group_state", ["archived", "deleted"])
async def test_retained_group_is_read_only_even_for_super_admin(roster, group_state):
    roster.group.status = group_state
    roster.actor.role = "super_admin"
    await roster.session.commit()
    with pytest.raises(HTTPException) as error:
        await save(roster, user=UserRepository._to_entity(roster.actor))
    assert error.value.status_code == 404
    assert not any(row.document_follow_up for row in roster.rows)


@pytest.mark.parametrize("restriction", ["coordinator", "client_manager", "other_agency", "unassigned_staff", "inactive", "role_changed"])
async def test_permission_boundaries_are_revalidated(roster, restriction):
    user = roster.user
    if restriction in {"coordinator", "client_manager"}:
        user = replace(user, role=UserRole.AGENCY_COORDINATOR if restriction == "coordinator" else UserRole.CLIENT_MANAGER)
    elif restriction == "other_agency":
        agency = AgencyModel(id=uuid.uuid4(), name="Other", email=f"{uuid.uuid4()}@example.test")
        roster.session.add(agency)
        await roster.session.flush()
        roster.actor.agency_id = agency.id
        await roster.session.commit()
        user = UserRepository._to_entity(roster.actor)
    elif restriction == "unassigned_staff":
        roster.actor.role = "agency_staff"
        roster.group.created_by_user_id = None
        await roster.session.commit()
        user = UserRepository._to_entity(roster.actor)
    elif restriction == "inactive":
        roster.actor.is_active = False
        await roster.session.commit()
    else:
        roster.actor.role = "agency_coordinator"
        await roster.session.commit()
    with pytest.raises(HTTPException) as error:
        await save(roster, user=user)
    assert error.value.status_code in {403, 404}
    assert not any(row.document_follow_up for row in roster.rows)


def test_bulk_route_requires_auth_csrf_and_bounded_selection():
    dependencies = {item.call for item in router.routes[0].dependant.dependencies}
    assert {get_current_active_user, require_cookie_csrf} <= dependencies
    for ids in ([], [uuid.uuid4()] * 1501):
        with pytest.raises(ValidationError):
            BulkDocumentFollowUpRequest(submission_ids=ids, flagged=True)
    public = {"upload_passport", "get_upload_passport_status", "scan_again_public_upload", "client_submit_passport"}
    for route in passports_router.routes:
        if route.name in public:
            assert "document_follow_up" in route.response_model_exclude
