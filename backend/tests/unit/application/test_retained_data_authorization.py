"""Database-backed regression matrix for retained passport access boundaries."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.client_groups.restore_client_group_use_case import (
    RestoreClientGroupUseCase,
)
from app.application.use_cases.passports.get_passport_submission_use_case import (
    GetPassportSubmissionUseCase,
)
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    ManagerGroupAccessModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.routes import (
    client_groups,
    search,
    tour_operations,
    tour_operations_assignments,
    tour_operations_attendance_sessions,
)
from app.presentation.api.v1.routes.passport_routes import (
    covers,
    excel_exports,
    image_support,
    submission_review,
)


@pytest.fixture
async def retained_records(db_session):
    agency_id, foreign_agency_id, user_id, other_user_id = (uuid.uuid4() for _ in range(4))
    db_session.add_all([
        AgencyModel(id=agency_id, name="Synthetic office", email="office@example.test"),
        AgencyModel(id=foreign_agency_id, name="Other office", email="other@example.test"),
    ])
    await db_session.flush()
    db_session.add_all([
        UserModel(id=user_id, agency_id=agency_id, email="reader@example.test", full_name="Reader", hashed_password="unused", role="agency_staff"),
        UserModel(id=other_user_id, agency_id=agency_id, email="owner@example.test", full_name="Owner", hashed_password="unused", role="agency_staff"),
    ])
    await db_session.flush()
    records = []
    for relation in ("owned", "assigned", "unassigned", "foreign"):
        for lifecycle in ("active", "closed", "archived", "deleted", "tombstone"):
            tenant = foreign_agency_id if relation == "foreign" else agency_id
            group = ClientGroupModel(
                id=uuid.uuid4(), agency_id=tenant,
                created_by_user_id=user_id if relation == "owned" else other_user_id,
                name=f"Needle {relation} {lifecycle}", token=uuid.uuid4().hex,
                status="active" if lifecycle == "tombstone" else lifecycle,
                deleted_at=datetime.now(UTC) if lifecycle in {"deleted", "tombstone"} else None,
                deletion_retained_records=lifecycle == "deleted",
            )
            db_session.add(group)
            await db_session.flush()
            passport = PassportSubmissionModel(
                id=uuid.uuid4(), agency_id=tenant, group_id=group.id,
                client_name=f"Needle {relation} {lifecycle}",
                image_s3_key="synthetic/front.jpg", passport_cover_s3_key="synthetic/cover.jpg",
                status="submitted", extracted_fields={"passport_number": "SYNTHETIC"},
            )
            db_session.add(passport)
            await db_session.flush()
            if relation in {"assigned", "foreign"}:
                # Even a stale cross-tenant assignment cannot grant visibility.
                db_session.add(ManagerGroupAccessModel(manager_id=user_id, group_id=group.id, agency_id=tenant))
                db_session.add(CoordinatorGroupAssignmentModel(coordinator_user_id=user_id, group_id=group.id, agency_id=tenant, active=True))
                db_session.add(CoordinatorAssignmentModel(coordinator_user_id=user_id, group_id=group.id, passenger_id=passport.id, agency_id=tenant, active=True))
            records.append((relation, lifecycle, group, passport))
    await db_session.flush()
    user = User(id=user_id, agency_id=agency_id, email="reader@example.test", full_name="Reader", hashed_password="unused", role=UserRole.AGENCY_STAFF)
    return user, records


def _expected(role, relation, lifecycle):
    if role == UserRole.SUPER_ADMIN:
        return True
    if relation == "foreign" or lifecycle in {"deleted", "tombstone"}:
        return False
    if role in {UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER}:
        return True
    if lifecycle == "archived":
        return False
    if role == UserRole.AGENCY_STAFF:
        return relation in {"owned", "assigned"}
    if role == UserRole.AGENCY_COORDINATOR:
        return relation == "assigned"
    return False


@pytest.mark.parametrize("role", list(UserRole))
async def test_query_search_and_object_decisions_agree_for_every_lifecycle(db_session, retained_records, role):
    user, records = retained_records
    user.role = role
    policy = AuthorizationPolicy(db_session)
    expected_groups = set()
    expected_passports = set()
    for relation, lifecycle, group, passport in records:
        allowed = _expected(role, relation, lifecycle)
        assert await policy.can_view_group(user, group) is allowed, (role, relation, lifecycle)
        assert await policy.can_view_passport(user, passport) is allowed, (role, relation, lifecycle)
        office_allowed = allowed and role != UserRole.AGENCY_COORDINATOR
        assert await policy.can_manage_group(user, group) is office_allowed
        assert await policy.can_export_data(user, group) is office_allowed
        assert await policy.can_confirm_passport(user, passport) is office_allowed
        if allowed:
            expected_groups.add(group.id)
            expected_passports.add(passport.id)
    assert set(await db_session.scalars(policy.apply_group_visibility_scope(select(ClientGroupModel.id), user))) == expected_groups
    assert set(await db_session.scalars(policy.apply_passport_visibility_scope(select(PassportSubmissionModel.id), user))) == expected_passports
    # Both forms matter: passport lists do not require a group join, search does.
    passport_results = await search._search_passports(db_session, user, "needle", 100)
    group_results = await search._search_groups(db_session, user, "needle", 100)
    assert {row.id for row in passport_results} == expected_passports
    assert {row.id for row in group_results} == expected_groups


@pytest.mark.parametrize("role", [UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF, UserRole.AGENCY_COORDINATOR])
async def test_deleted_known_ids_fail_before_detail_image_cover_export_or_write_side_effects(db_session, retained_records, monkeypatch, role):
    user, records = retained_records
    user.role = role
    _, _, group, passport = next(row for row in records if row[:2] == ("assigned", "deleted"))
    storage = Mock(side_effect=AssertionError("Denied requests must not initialize storage"))
    monkeypatch.setattr(covers, "MinioStorageRepository", storage)
    response = AsyncMock(side_effect=AssertionError("Denied detail must not prepare document URLs"))
    monkeypatch.setattr(submission_review, "_response_from_dto", response)
    export = AsyncMock(side_effect=AssertionError("Denied export must not load its payload"))
    monkeypatch.setattr(excel_exports, "_current_group_export_submissions", export)
    retry = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("Denied writes must not execute")))
    repo = PassportSubmissionRepository(db_session)
    calls = [
        lambda: submission_review.get_passport(passport.id, BackgroundTasks(), current_user=user, use_case=GetPassportSubmissionUseCase(repo), session=db_session),
        lambda: image_support._authorized_staff_passport_image(submission_id=passport.id, image_type=PassportImageType.PASSPORT_FRONT, current_user=user, session=db_session, require_editor=False),
        lambda: image_support._authorized_staff_passport_image(submission_id=passport.id, image_type=PassportImageType.PASSPORT_FRONT, current_user=user, session=db_session, require_editor=True),
        lambda: covers.get_passport_cover(passport.id, "cover", current_user=user, session=db_session),
        lambda: excel_exports.export_passports_by_group(group.id, current_user=user, session=db_session),
        lambda: submission_review.retry_post_submission_verification(passport.id, BackgroundTasks(), current_user=user, get_use_case=GetPassportSubmissionUseCase(repo), retry_use_case=retry, session=db_session),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as caught:
            await call()
        assert caught.value.status_code == 403
    storage.assert_not_called()
    response.assert_not_awaited()
    export.assert_not_awaited()
    retry.execute.assert_not_awaited()
    with pytest.raises(AuthorizationError):
        await AuthorizationPolicy(db_session).require_confirm_passport(user, passport)


@pytest.mark.parametrize("role", [UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.SUPER_ADMIN])
async def test_archive_listing_reads_and_restore_keep_authorized_office_workflow(db_session, retained_records, monkeypatch, role):
    user, records = retained_records
    user.role = role
    _, _, group, passport = next(row for row in records if row[:2] == ("assigned", "archived"))
    repo = ClientGroupRepository(db_session)
    archived = await repo.list_by_agency(user.agency_id, status_filter="archived", visible_to_user=user)
    assert group.id in {row.id for row in archived}
    submission, key = await image_support._authorized_staff_passport_image(submission_id=passport.id, image_type=PassportImageType.PASSPORT_FRONT, current_user=user, session=db_session, require_editor=False)
    assert submission.id == passport.id and key == "synthetic/front.jpg"
    stream = AsyncMock(return_value="synthetic-cover")
    monkeypatch.setattr(covers, "private_object_streaming_response", stream)
    monkeypatch.setattr(covers, "MinioStorageRepository", Mock())
    assert await covers.get_passport_cover(passport.id, "cover", current_user=user, session=db_session) == "synthetic-cover"
    monkeypatch.setattr(client_groups, "sync_group_broadcast_contacts", AsyncMock())
    restored = await client_groups.restore_client_group(group.id, current_user=user, use_case=RestoreClientGroupUseCase(repo), session=db_session)
    assert restored.status == "active"


async def test_super_admin_retained_access_and_restore_are_explicit_capabilities(db_session, retained_records, monkeypatch):
    user, records = retained_records
    _, _, group, passport = next(row for row in records if row[:2] == ("assigned", "deleted"))
    user.role = UserRole.AGENCY_ADMIN
    policy = AuthorizationPolicy(db_session)
    assert not policy.can_access_retained_data(user)
    # Permanent-delete retries remain a separate capability; ordinary reads deny.
    assert await policy.can_delete_data(user, group, permanent=True)
    assert not await policy.can_delete_data(user, group)
    with pytest.raises(HTTPException) as caught:
        await client_groups.restore_client_group(group.id, current_user=user, use_case=RestoreClientGroupUseCase(ClientGroupRepository(db_session)), session=db_session)
    assert caught.value.status_code == 403
    user.role = UserRole.SUPER_ADMIN
    assert policy.can_access_retained_data(user)
    assert await policy.can_view_passport(user, passport)
    submission, _ = await image_support._authorized_staff_passport_image(submission_id=passport.id, image_type=PassportImageType.PASSPORT_FRONT, current_user=user, session=db_session, require_editor=False)
    assert submission.id == passport.id
    monkeypatch.setattr(client_groups, "sync_group_broadcast_contacts", AsyncMock())
    restored = await client_groups.restore_client_group(group.id, current_user=user, use_case=RestoreClientGroupUseCase(ClientGroupRepository(db_session)), session=db_session)
    assert restored.status == "active"


@pytest.mark.parametrize("role", list(UserRole))
async def test_missing_or_mismatched_parent_denies_passport_access(db_session, retained_records, role):
    user, records = retained_records
    user.role = role
    foreign_group = next(group for relation, lifecycle, group, _ in records if relation == "foreign" and lifecycle == "active")
    policy = AuthorizationPolicy(db_session)
    missing = SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4(), agency_id=user.agency_id)
    mismatch = PassportSubmissionModel(id=uuid.uuid4(), group_id=foreign_group.id, agency_id=user.agency_id, client_name="Malformed synthetic passport", image_s3_key="unused", status="submitted")
    # 0108 now rejects this malformed graph at persistence as well as at the
    # policy boundary. Preserve the explicit object-policy regression.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(mismatch)
            await db_session.flush()
    assert not await policy.can_view_passport(user, missing)
    assert not await policy.can_view_passport(user, mismatch)
    visible = set(await db_session.scalars(policy.apply_passport_visibility_scope(select(PassportSubmissionModel.id), user)))
    assert mismatch.id not in visible


async def test_raw_staff_filters_used_by_email_consumers_do_not_reintroduce_retained_data(db_session, retained_records):
    user, records = retained_records
    expected = {group.id for relation, lifecycle, group, _ in records if _expected(user.role, relation, lifecycle)}
    groups = await db_session.scalars(select(ClientGroupModel.id).where(AuthorizationPolicy.staff_group_visibility_filter(user)))
    passports = await db_session.scalars(select(PassportSubmissionModel.group_id).where(AuthorizationPolicy.staff_passport_visibility_filter(user)))
    assert set(groups) == expected
    assert set(passports) == expected


@pytest.mark.parametrize("dated", [False, True], ids=["undated", "future"])
async def test_coordinator_group_list_and_known_attendance_session_share_lifecycle_boundary(
    db_session, retained_records, monkeypatch, dated,
):
    user, records = retained_records
    user.role = UserRole.AGENCY_COORDINATOR
    attendance = []
    for relation, lifecycle, group, passport in records:
        if relation not in {"assigned", "foreign"}:
            continue
        if dated:
            group.travel_date = date.today() + timedelta(days=5)
            group.return_date = date.today() + timedelta(days=7)
        session_id = uuid.uuid4()
        activity = AttendanceSessionModel(
            id=session_id, canonical_session_id=session_id,
            agency_id=user.agency_id, group_id=group.id,
            name=f"Synthetic {relation} {lifecycle}", normalized_name=f"{relation}-{lifecycle}",
            status="active", created_by_user_id=user.id,
        )
        db_session.add(activity)
        attendance.append((relation, lifecycle, group, passport, activity))
    await db_session.flush()

    hydrated_groups = AsyncMock(side_effect=lambda _session, groups: groups)
    hydrated_details = AsyncMock(return_value="synthetic-details")
    monkeypatch.setattr(tour_operations_assignments, "_group_responses", hydrated_groups)
    monkeypatch.setattr(tour_operations_attendance_sessions, "_attendance_session_details_response", hydrated_details)
    groups = await tour_operations.list_my_coordinator_groups(current_user=user, session=db_session)
    allowed_groups = {group.id for relation, lifecycle, group, _, _ in attendance if relation == "assigned" and lifecycle in {"active", "closed"}}
    assert {group.id for group in groups} == allowed_groups
    assert {group.id for group in hydrated_groups.await_args.args[1]} == allowed_groups

    for relation, lifecycle, group, passport, activity in attendance:
        hydrated_details.reset_mock()
        if group.id in allowed_groups:
            assert await tour_operations.get_my_attendance_session_details(activity.id, current_user=user, session=db_session) == "synthetic-details"
            assert hydrated_details.await_args.args[1].id == activity.id
        else:
            with pytest.raises(HTTPException) as caught:
                await tour_operations.get_my_attendance_session_details(activity.id, current_user=user, session=db_session)
            assert caught.value.status_code == 404, (relation, lifecycle)
            hydrated_details.assert_not_awaited()
            # The write/scan lookup applies the same decision under its lock.
            with pytest.raises(HTTPException) as locked:
                await tour_operations._get_coordinator_attendance_session(db_session, user.agency_id, activity.id, user.id, lock_for_scan=True)
            assert locked.value.status_code == 404
        # The check must not delete historical sessions, passengers or assignments.
        assert await db_session.get(PassportSubmissionModel, passport.id) is passport
        assert await db_session.get(AttendanceSessionModel, activity.id) is activity
