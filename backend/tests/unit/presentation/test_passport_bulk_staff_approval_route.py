from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import GroupStatus, User, UserRole
from app.infrastructure.database.models import PassportSubmissionModel, UserModel
from app.infrastructure.observability.operational_events import OperationalEvent
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.routes.passports import (
    _lock_active_bulk_approval_actor,
    bulk_staff_approve_passport_submissions,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkDeletePassportSubmissionsRequest,
    BulkStaffApprovePassportSubmissionsRequest,
    ExportSelectedPassportsRequest,
)


class _ScalarResult:
    def __init__(self, rows: list[PassportSubmissionModel]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[PassportSubmissionModel]:
        return self._rows


class _SingleResult:
    def __init__(self, row: UserModel | None) -> None:
        self._row = row

    def scalar_one_or_none(self) -> UserModel | None:
        return self._row


@pytest.fixture(autouse=True)
def _use_request_actor_for_route_behavior_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _same_actor(_session: object, current_user: User) -> User:
        return current_user

    monkeypatch.setattr(
        "app.presentation.api.v1.routes.passports._lock_active_bulk_approval_actor",
        _same_actor,
    )


def _user(*, role: UserRole = UserRole.SUPER_ADMIN) -> User:
    return User(
        id=uuid.uuid4(),
        email="reviewer@example.com",
        hashed_password="unused",
        full_name="Bulk Reviewer",
        role=role,
        agency_id=None if role is UserRole.SUPER_ADMIN else uuid.uuid4(),
    )


def _submission(
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    status: str,
) -> PassportSubmissionModel:
    now = datetime.now(tz=UTC)
    return PassportSubmissionModel(
        id=uuid.uuid4(),
        group_id=group_id,
        agency_id=agency_id,
        client_name="Passenger",
        image_s3_key=f"drafts/{agency_id}/{group_id}/{uuid.uuid4()}.jpg",
        acquisition_mode="file",
        extraction_status="extraction_complete",
        extraction_revision=4,
        status=status,
        post_submission_verification_revision=2,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_bulk_approval_actor_is_revalidated_under_lock() -> None:
    reviewer = _user(role=UserRole.AGENCY_ADMIN)
    now = datetime.now(tz=UTC)
    actor_model = UserModel(
        id=reviewer.id,
        email=reviewer.email,
        hashed_password=reviewer.hashed_password,
        full_name=reviewer.full_name,
        role=reviewer.role.value,
        agency_id=reviewer.agency_id,
        is_active=True,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    session = SimpleNamespace(execute=AsyncMock(return_value=_SingleResult(actor_model)))

    actor = await _lock_active_bulk_approval_actor(
        session,  # type: ignore[arg-type]
        reviewer,
    )

    assert actor.id == reviewer.id
    assert actor.role is reviewer.role
    assert actor.agency_id == reviewer.agency_id
    statement = session.execute.await_args.args[0]
    assert statement._for_update_arg is not None
    statement_text = str(statement)
    assert "users.role" in statement_text
    assert "users.agency_id" in statement_text
    assert "users.is_active" in statement_text


@pytest.mark.asyncio
async def test_bulk_approval_actor_change_fails_closed() -> None:
    reviewer = _user(role=UserRole.AGENCY_STAFF)
    session = SimpleNamespace(execute=AsyncMock(return_value=_SingleResult(None)))

    with pytest.raises(HTTPException) as caught:
        await _lock_active_bulk_approval_actor(
            session,  # type: ignore[arg-type]
            reviewer,
        )

    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_bulk_staff_approval_is_atomic_audited_and_reports_skips() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    reviewer = _user()
    models = [
        _submission(group_id=group_id, agency_id=agency_id, status="confirmed"),
        _submission(group_id=group_id, agency_id=agency_id, status="ai_approved"),
        _submission(group_id=group_id, agency_id=agency_id, status="needs_review"),
        _submission(group_id=group_id, agency_id=agency_id, status="submitted"),
        _submission(group_id=group_id, agency_id=agency_id, status="client_submitted"),
        _submission(group_id=group_id, agency_id=agency_id, status="staff_approved"),
        _submission(group_id=group_id, agency_id=agency_id, status="processing"),
        _submission(group_id=group_id, agency_id=agency_id, status="confirmed"),
    ]
    models[7].extraction_revision = 5
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(models)),
        add_all=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    ensure_qrs = AsyncMock(return_value=[])

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=SimpleNamespace(id=group_id, agency_id=agency_id)),
        ),
        patch.object(AuthorizationPolicy, "can_view_group", AsyncMock(return_value=True)),
        patch(
            "app.presentation.api.v1.routes.passports.ensure_approved_passenger_qrs",
            ensure_qrs,
        ),
        patch("app.presentation.api.v1.routes.passports.record_operational_event") as record_event,
    ):
        response = await bulk_staff_approve_passport_submissions(
            group_id=group_id,
            body=BulkStaffApprovePassportSubmissionsRequest(
                submissions=[
                    {
                        "submission_id": model.id,
                        "expected_extraction_revision": 4,
                    }
                    for model in models
                ]
            ),
            response=Response(),
            _csrf=None,
            current_user=reviewer,
            session=session,  # type: ignore[arg-type]
        )

    assert response.requested_count == 8
    assert response.approved_count == 5
    assert response.already_approved_count == 1
    assert response.skipped_count == 2
    assert response.skipped_submissions[0].submission_id == models[6].id
    assert response.skipped_submissions[0].current_status == "processing"
    assert response.skipped_submissions[0].reason == "not_completed"
    assert response.skipped_submissions[1].submission_id == models[7].id
    assert response.skipped_submissions[1].reason == "stale"
    assert response.skipped_submissions[1].expected_extraction_revision == 4
    assert response.skipped_submissions[1].current_extraction_revision == 5
    assert [model.status for model in models] == [
        "staff_approved",
        "staff_approved",
        "staff_approved",
        "staff_approved",
        "staff_approved",
        "staff_approved",
        "processing",
        "confirmed",
    ]
    assert all(model.extraction_revision == 5 for model in models[:5])
    assert models[5].extraction_revision == 4
    assert models[6].extraction_revision == 4
    assert models[7].extraction_revision == 5
    session.add_all.assert_called_once()
    audit_rows = session.add_all.call_args.args[0]
    assert len(audit_rows) == 5
    assert {row.entity_id for row in audit_rows} == {str(model.id) for model in models[:5]}
    assert all(row.action == "passport_staff_approved" for row in audit_rows)
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()
    ensure_qrs.assert_awaited_once()
    assert set(ensure_qrs.await_args.args[1]) == {model.id for model in models[:5]}
    locked_query = session.execute.await_args.args[0]
    assert locked_query._for_update_arg is not None
    assert "client_groups.status NOT IN" in str(locked_query)
    record_event.assert_any_call(
        OperationalEvent.STAFF_APPROVAL,
        "approved",
        amount=5,
    )
    record_event.assert_any_call(
        OperationalEvent.STAFF_APPROVAL,
        "already_approved",
        amount=1,
    )
    record_event.assert_any_call(
        OperationalEvent.STAFF_APPROVAL,
        "skipped",
        amount=2,
    )


@pytest.mark.asyncio
async def test_bulk_staff_approval_rolls_back_when_qr_issuance_fails() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    model = _submission(group_id=group_id, agency_id=agency_id, status="confirmed")
    reviewer = _user()
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult([model])),
        add_all=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=SimpleNamespace(id=group_id, agency_id=agency_id)),
        ),
        patch.object(AuthorizationPolicy, "can_view_group", AsyncMock(return_value=True)),
        patch(
            "app.presentation.api.v1.routes.passports.ensure_approved_passenger_qrs",
            AsyncMock(side_effect=RuntimeError("QR unavailable")),
        ),
        patch("app.presentation.api.v1.routes.passports.record_operational_event") as record_event,
        pytest.raises(RuntimeError, match="QR unavailable"),
    ):
        await bulk_staff_approve_passport_submissions(
            group_id=group_id,
            body=BulkStaffApprovePassportSubmissionsRequest(
                submissions=[
                    {
                        "submission_id": model.id,
                        "expected_extraction_revision": model.extraction_revision,
                    }
                ]
            ),
            response=Response(),
            _csrf=None,
            current_user=reviewer,
            session=session,  # type: ignore[arg-type]
        )

    session.rollback.assert_awaited_once_with()
    session.commit.assert_not_awaited()
    record_event.assert_called_once_with(
        OperationalEvent.STAFF_APPROVAL,
        "unexpected_failure",
        amount=1,
    )


@pytest.mark.asyncio
async def test_bulk_staff_approval_rejects_group_without_visibility() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    session = SimpleNamespace(execute=AsyncMock())

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=SimpleNamespace(id=group_id, agency_id=agency_id)),
        ),
        patch.object(AuthorizationPolicy, "can_view_group", AsyncMock(return_value=False)),
        pytest.raises(HTTPException) as caught,
    ):
        await bulk_staff_approve_passport_submissions(
            group_id=group_id,
            body=BulkStaffApprovePassportSubmissionsRequest(
                submissions=[
                    {
                        "submission_id": uuid.uuid4(),
                        "expected_extraction_revision": 0,
                    }
                ]
            ),
            response=Response(),
            _csrf=None,
            current_user=_user(role=UserRole.AGENCY_STAFF),
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 403
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_staff_approval_rejects_soft_deleted_group() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    session = SimpleNamespace(execute=AsyncMock())
    can_view_group = AsyncMock(return_value=True)

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(
                return_value=SimpleNamespace(
                    id=group_id,
                    agency_id=agency_id,
                    deleted_at=datetime.now(tz=UTC),
                )
            ),
        ),
        patch.object(AuthorizationPolicy, "can_view_group", can_view_group),
        pytest.raises(HTTPException) as caught,
    ):
        await bulk_staff_approve_passport_submissions(
            group_id=group_id,
            body=BulkStaffApprovePassportSubmissionsRequest(
                submissions=[
                    {
                        "submission_id": uuid.uuid4(),
                        "expected_extraction_revision": 0,
                    }
                ]
            ),
            response=Response(),
            _csrf=None,
            current_user=_user(role=UserRole.AGENCY_ADMIN),
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 404
    can_view_group.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_staff_approval_rejects_archived_group() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    session = SimpleNamespace(execute=AsyncMock())
    can_view_group = AsyncMock(return_value=True)

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(
                return_value=SimpleNamespace(
                    id=group_id,
                    agency_id=agency_id,
                    status=GroupStatus.ARCHIVED,
                    deleted_at=None,
                )
            ),
        ),
        patch.object(AuthorizationPolicy, "can_view_group", can_view_group),
        pytest.raises(HTTPException) as caught,
    ):
        await bulk_staff_approve_passport_submissions(
            group_id=group_id,
            body=BulkStaffApprovePassportSubmissionsRequest(
                submissions=[
                    {
                        "submission_id": uuid.uuid4(),
                        "expected_extraction_revision": 0,
                    }
                ]
            ),
            response=Response(),
            _csrf=None,
            current_user=_user(role=UserRole.AGENCY_ADMIN),
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 404
    can_view_group.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_staff_approval_rejects_non_office_role_before_group_lookup() -> None:
    group_lookup = AsyncMock()
    session = SimpleNamespace(execute=AsyncMock())

    with (
        patch.object(ClientGroupRepository, "get_by_id", group_lookup),
        pytest.raises(HTTPException) as caught,
    ):
        await bulk_staff_approve_passport_submissions(
            group_id=uuid.uuid4(),
            body=BulkStaffApprovePassportSubmissionsRequest(
                submissions=[
                    {
                        "submission_id": uuid.uuid4(),
                        "expected_extraction_revision": 0,
                    }
                ]
            ),
            response=Response(),
            _csrf=None,
            current_user=_user(role=UserRole.AGENCY_COORDINATOR),
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 403
    group_lookup.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_staff_approval_rejects_foreign_or_missing_selected_ids() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    visible_model = _submission(
        group_id=group_id,
        agency_id=agency_id,
        status="confirmed",
    )
    missing_id = uuid.uuid4()
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult([visible_model])),
        commit=AsyncMock(),
    )
    ensure_qrs = AsyncMock()

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=SimpleNamespace(id=group_id, agency_id=agency_id)),
        ),
        patch.object(AuthorizationPolicy, "can_view_group", AsyncMock(return_value=True)),
        patch(
            "app.presentation.api.v1.routes.passports.ensure_approved_passenger_qrs",
            ensure_qrs,
        ),
        pytest.raises(HTTPException) as caught,
    ):
        await bulk_staff_approve_passport_submissions(
            group_id=group_id,
            body=BulkStaffApprovePassportSubmissionsRequest(
                submissions=[
                    {
                        "submission_id": visible_model.id,
                        "expected_extraction_revision": 4,
                    },
                    {
                        "submission_id": missing_id,
                        "expected_extraction_revision": 0,
                    },
                ]
            ),
            response=Response(),
            _csrf=None,
            current_user=_user(),
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 404
    session.commit.assert_not_awaited()
    ensure_qrs.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_staff_approval_retry_is_idempotent_without_qr_reissuance() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    model = _submission(
        group_id=group_id,
        agency_id=agency_id,
        status="staff_approved",
    )
    original_revision = model.extraction_revision
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult([model])),
        add_all=Mock(),
        flush=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    ensure_qrs = AsyncMock()

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=SimpleNamespace(id=group_id, agency_id=agency_id)),
        ),
        patch.object(AuthorizationPolicy, "can_view_group", AsyncMock(return_value=True)),
        patch(
            "app.presentation.api.v1.routes.passports.ensure_approved_passenger_qrs",
            ensure_qrs,
        ),
        patch("app.presentation.api.v1.routes.passports.record_operational_event") as record_event,
    ):
        result = await bulk_staff_approve_passport_submissions(
            group_id=group_id,
            body=BulkStaffApprovePassportSubmissionsRequest(
                submissions=[
                    {
                        "submission_id": model.id,
                        # A retry is idempotent even if the caller retained the
                        # pre-approval snapshot revision.
                        "expected_extraction_revision": original_revision - 1,
                    }
                ]
            ),
            response=Response(),
            _csrf=None,
            current_user=_user(),
            session=session,  # type: ignore[arg-type]
        )

    assert result.approved_count == 0
    assert result.already_approved_count == 1
    assert result.skipped_count == 0
    assert model.extraction_revision == original_revision
    session.add_all.assert_not_called()
    ensure_qrs.assert_not_awaited()
    session.commit.assert_awaited_once_with()
    session.rollback.assert_not_awaited()
    record_event.assert_called_once_with(
        OperationalEvent.STAFF_APPROVAL,
        "already_approved",
        amount=1,
    )


@pytest.mark.asyncio
async def test_bulk_staff_approval_rejects_conflicting_duplicate_snapshots() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    submission_id = uuid.uuid4()
    session = SimpleNamespace(execute=AsyncMock())

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id",
            AsyncMock(return_value=SimpleNamespace(id=group_id, agency_id=agency_id)),
        ),
        patch.object(AuthorizationPolicy, "can_view_group", AsyncMock(return_value=True)),
        pytest.raises(HTTPException) as caught,
    ):
        await bulk_staff_approve_passport_submissions(
            group_id=group_id,
            body=BulkStaffApprovePassportSubmissionsRequest(
                submissions=[
                    {
                        "submission_id": submission_id,
                        "expected_extraction_revision": 3,
                    },
                    {
                        "submission_id": submission_id,
                        "expected_extraction_revision": 4,
                    },
                ]
            ),
            response=Response(),
            _csrf=None,
            current_user=_user(),
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 400
    session.execute.assert_not_awaited()


def test_selected_action_requests_accept_1500_ids_and_reject_1501() -> None:
    ids = [uuid.uuid4() for _ in range(1501)]
    for request_type in (ExportSelectedPassportsRequest, BulkDeletePassportSubmissionsRequest):
        assert len(request_type(submission_ids=ids[:1500]).submission_ids) == 1500
        with pytest.raises(ValidationError):
            request_type(submission_ids=ids)
    selections = [
        {"submission_id": submission_id, "expected_extraction_revision": 0} for submission_id in ids
    ]
    assert (
        len(BulkStaffApprovePassportSubmissionsRequest(submissions=selections[:1500]).submissions)
        == 1500
    )
    with pytest.raises(ValidationError):
        BulkStaffApprovePassportSubmissionsRequest(submissions=selections)
