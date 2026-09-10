"""Client-detail correction boundary: scope, concurrency, audit and delivery fences."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Response
from sqlalchemy.dialects import postgresql

from app.domain.entities.entities import GroupStatus, PassportProcessingStatus, User, UserRole
from app.infrastructure.whatsapp.private_delivery_policy import PrivateDeliveryMutationBlocked
from app.presentation.api.v1.routes.passport_routes import client_details as routes
from app.presentation.api.v1.schemas.passport_client_details_schemas import (
    UpdatePassportClientDetailsRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf
from tests.unit.application.test_correct_client_details import sample


@pytest.fixture
def rig():
    submission, group = sample()
    user = User(
        uuid.uuid4(),
        "reviewer@example.com",
        "not-a-password",
        "Reviewer",
        UserRole.AGENCY_ADMIN,
        submission.agency_id,
    )
    events = []
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: object())
    session.commit.side_effect = lambda: events.append("commit")
    repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=submission),
        get_by_id_for_update=AsyncMock(return_value=submission),
        update=AsyncMock(),
    )
    repo.update.side_effect = lambda value: events.append("update")
    repo.get_by_id_for_update.side_effect = lambda _id: (
        events.append("submission_lock"),
        submission,
    )[1]
    group_repo = SimpleNamespace(get_by_id=AsyncMock(return_value=group))
    audit = SimpleNamespace(record=AsyncMock(side_effect=lambda **kwargs: events.append("audit")))
    propagate = AsyncMock(side_effect=lambda *args, **kwargs: events.append("propagate"))
    guard = AsyncMock(side_effect=lambda *args, **kwargs: (events.append("private_guard"), 2)[1])
    response_builder = AsyncMock(return_value=object())
    with (
        patch.object(routes, "PassportSubmissionRepository", return_value=repo),
        patch.object(routes, "ClientGroupRepository", return_value=group_repo),
        patch.object(routes, "AuditLogRepository", return_value=audit),
        patch.object(routes, "propagate_mobile_passenger_change", new=propagate),
        patch.object(routes, "prepare_private_delivery_identity_mutation", new=guard),
        patch.object(routes, "_response_from_submission", new=response_builder),
    ):
        yield SimpleNamespace(
            submission=submission,
            group=group,
            user=user,
            session=session,
            repo=repo,
            group_repo=group_repo,
            audit=audit,
            propagate=propagate,
            guard=guard,
            response_builder=response_builder,
            events=events,
        )


async def save(rig, **changes):
    body = UpdatePassportClientDetailsRequest(
        expected_updated_at=rig.submission.updated_at, **changes
    )
    return await routes.update_passport_client_details(
        rig.submission.id, body, Response(), current_user=rig.user, session=rig.session
    )


async def test_authorized_correction_commits_audit_profile_refresh_and_private_guard(rig):
    result = await save(rig, agent_employee_code="12345")
    assert result is rig.response_builder.return_value
    assert rig.events == [
        "private_guard",
        "submission_lock",
        "update",
        "audit",
        "propagate",
        "commit",
    ]
    statement = rig.session.execute.await_args.args[0]
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
    assert statement.get_execution_options()["populate_existing"] is True
    rig.guard.assert_awaited_once()
    assert rig.guard.await_args.kwargs["group_id"] == rig.submission.group_id
    assert rig.guard.await_args.kwargs["cancel_queued"] is True
    audit = rig.audit.record.await_args.kwargs
    assert audit["user_id"] == rig.user.id
    assert audit["metadata"]["changed_fields"] == ["agent_employee_code"]
    assert audit["metadata"]["cancelled_private_deliveries"] == 2
    assert "12345" not in str(audit)
    assert rig.propagate.await_args.kwargs["change_kind"] == "profile"
    assert rig.propagate.await_args.kwargs["reconcile_identities"] is True
    updated = rig.repo.update.await_args.args[0]
    assert updated.status == rig.submission.status
    assert updated.post_submission_verification == rig.submission.post_submission_verification
    assert (
        updated.post_submission_verification_revision
        == rig.submission.post_submission_verification_revision
    )


async def test_custom_answer_correction_also_reconciles_private_identity(rig):
    await save(
        rig,
        custom_answers=[{"question_id": rig.group.custom_questions[0]["id"], "value": "Window"}],
    )
    assert rig.propagate.await_args.kwargs["reconcile_identities"] is True
    rig.guard.assert_awaited_once()


async def test_concurrent_write_detected_after_locked_fresh_read(rig):
    rig.repo.get_by_id_for_update.side_effect = None
    rig.repo.get_by_id_for_update.return_value = replace(
        rig.submission, updated_at=rig.submission.updated_at + timedelta(microseconds=1)
    )
    with pytest.raises(HTTPException) as error:
        await save(rig, agent_employee_code="12345")
    assert error.value.status_code == 409
    rig.repo.update.assert_not_awaited()
    rig.session.commit.assert_not_awaited()
    rig.session.rollback.assert_awaited_once()


async def test_noop_does_not_cancel_queued_deliveries_or_emit_audit_or_profile_work(rig):
    await save(rig, meal_preference="Veg")
    rig.guard.assert_not_awaited()
    rig.repo.update.assert_not_awaited()
    rig.audit.record.assert_not_awaited()
    rig.propagate.assert_not_awaited()


async def test_invalid_changes_do_not_cancel_deliveries(rig):
    with pytest.raises(HTTPException) as error:
        await save(rig, meal_preference="Invalid")
    assert error.value.status_code == 422
    rig.guard.assert_not_awaited()
    rig.repo.update.assert_not_awaited()


async def test_active_or_unknown_private_delivery_blocks_correction(rig):
    rig.guard.side_effect = PrivateDeliveryMutationBlocked(
        "A private WhatsApp delivery is in progress"
    )
    with pytest.raises(HTTPException) as error:
        await save(rig, agent_employee_code="12345")
    assert error.value.status_code == 409
    rig.repo.update.assert_not_awaited()
    rig.repo.get_by_id_for_update.assert_not_awaited()
    rig.audit.record.assert_not_awaited()
    rig.session.rollback.assert_awaited_once()


@pytest.mark.parametrize("failure", ["audit", "propagate", "commit"])
async def test_atomic_rollback_on_persistence_or_invalidation_failure(rig, failure):
    target = {"audit": rig.audit.record, "propagate": rig.propagate, "commit": rig.session.commit}[
        failure
    ]
    target.side_effect = RuntimeError("Synthetic failure")
    with pytest.raises(RuntimeError, match="Synthetic failure"):
        await save(rig, agent_employee_code="12345")
    rig.session.rollback.assert_awaited_once()
    rig.response_builder.assert_not_awaited()


@pytest.mark.parametrize(
    "role,foreign",
    [
        (UserRole.AGENCY_COORDINATOR, False),
        (UserRole.AGENCY_ADMIN, True),
        (UserRole.AGENCY_MANAGER, True),
    ],
)
async def test_read_and_edit_reject_coordinator_or_foreign_tenant(rig, role, foreign):
    rig.user.role = role
    if foreign:
        rig.user.agency_id = uuid.uuid4()
    with pytest.raises(HTTPException) as read_error:
        await routes.get_passport_client_details(
            rig.submission.id, Response(), rig.user, rig.session
        )
    assert read_error.value.status_code == 403
    with pytest.raises(HTTPException) as write_error:
        await save(rig, agent_employee_code="12345")
    assert write_error.value.status_code == 403
    rig.guard.assert_not_awaited()
    rig.repo.update.assert_not_awaited()


async def test_staff_requires_group_assignment(rig):
    rig.user.role = UserRole.AGENCY_STAFF
    with patch.object(
        routes.AuthorizationPolicy, "staff_can_access_group", new=AsyncMock(return_value=False)
    ):
        with pytest.raises(HTTPException) as error:
            await save(rig, agent_employee_code="12345")
    assert error.value.status_code == 403


@pytest.mark.parametrize("group_status", [GroupStatus.ARCHIVED, GroupStatus.DELETED])
async def test_archived_groups_are_not_editable(rig, group_status):
    rig.group.status = group_status
    with pytest.raises(HTTPException) as error:
        await save(rig, agent_employee_code="12345")
    assert error.value.status_code == 409
    rig.guard.assert_not_awaited()


async def test_public_draft_cannot_be_corrected_before_submission(rig):
    rig.submission.status = PassportProcessingStatus.READY_FOR_CLIENT_REVIEW
    with pytest.raises(HTTPException) as error:
        await save(rig, agent_employee_code="12345")
    assert error.value.status_code == 409


async def test_missing_submission_is_404(rig):
    rig.repo.get_by_id.return_value = None
    with pytest.raises(HTTPException) as error:
        await save(rig, agent_employee_code="12345")
    assert error.value.status_code == 404
    rig.guard.assert_not_awaited()


async def test_get_metadata_is_no_store_and_never_mutates(rig):
    response = Response()
    details = await routes.get_passport_client_details(
        rig.submission.id, response, rig.user, rig.session
    )
    assert response.headers["Cache-Control"] == "no-store"
    assert details.updated_at == rig.submission.updated_at
    rig.repo.update.assert_not_awaited()
    rig.guard.assert_not_awaited()


def test_routes_require_authenticated_staff_and_patch_cookie_csrf():
    get_route = next(
        route for route in routes.router.routes if route.name == "get_passport_client_details"
    )
    patch_route = next(
        route for route in routes.router.routes if route.name == "update_passport_client_details"
    )
    assert get_current_active_user in {dep.call for dep in get_route.dependant.dependencies}
    assert get_current_active_user in {dep.call for dep in patch_route.dependant.dependencies}
    assert require_cookie_csrf in {dep.call for dep in patch_route.dependant.dependencies}
