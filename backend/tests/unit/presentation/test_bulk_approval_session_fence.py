"""In-flight bulk approval honors completed credential and session revocation."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database.models import (
    AuditLogModel,
    PassportSubmissionModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.presentation.api.v1.routes import managed_account_sessions
from app.presentation.api.v1.routes.passport_routes import bulk_actions
from app.presentation.api.v1.schemas.passport_schemas import (
    BulkStaffApprovePassportSubmissionsRequest,
)
from tests.passport_image_mutations import seed_image_mutation_context
from tests.route_dependencies import set_route_dependency


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transition", ["unchanged", "profile_refresh", "legacy_no_state", "sessions_revoked", "credential_reset"]
)
async def test_bulk_approval_rechecks_the_authenticated_actor_session_before_writing(
    db_session, monkeypatch, transition
):
    context = await seed_image_mutation_context(db_session)
    submission_id = context.submission.id
    actor = context.actor
    await db_session.execute(
        update(PassportSubmissionModel).where(PassportSubmissionModel.id == submission_id)
        .values(status="client_submitted", extraction_status="extraction_complete",
                extraction_revision=4, confirmed_fields={"passport_number": "SYNTHETIC123"})
    )
    await db_session.commit()

    # The authenticated request already owns its immutable actor snapshot.
    # A separate completed transaction represents the normal management action.
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as writer:
        account = await writer.get(UserModel, actor.id)
        assert account is not None
        if transition == "sessions_revoked":
            await managed_account_sessions._fence_dashboard_sessions(writer, account)
        elif transition == "credential_reset":
            state = await IdentitySecurityRepository(writer).get_state(actor.id, lock=True)
            assert state is not None
            state.credential_state = "invited"
            state.session_version += 1
        elif transition == "profile_refresh":
            account.full_name = "Updated Reviewer"
        elif transition == "legacy_no_state":
            await writer.execute(delete(UserSecurityStateModel).where(
                UserSecurityStateModel.user_id == actor.id
            ))
        await writer.commit()

    qr = AsyncMock(return_value=[])
    set_route_dependency(monkeypatch, bulk_actions, "ensure_approved_passenger_qrs", qr)
    set_route_dependency(monkeypatch, bulk_actions, "propagate_mobile_passenger_change", AsyncMock())
    monkeypatch.setattr(
        "app.application.travellers.history_schedule.schedule_submission_history", AsyncMock()
    )
    error_status = None
    result = None
    try:
        result = await bulk_actions.bulk_staff_approve_passport_submissions(
            context.submission.group_id,
            BulkStaffApprovePassportSubmissionsRequest(submissions=[{
                "submission_id": submission_id, "expected_extraction_revision": 4,
            }]),
            Response(), _csrf=None, current_user=actor, session=db_session,
        )
    except HTTPException as error:
        error_status = error.status_code
    model = await db_session.get(PassportSubmissionModel, submission_id, populate_existing=True)
    assert model is not None
    rejected = transition in {"sessions_revoked", "credential_reset"}
    assert (error_status, model.status) == (
        (403, "client_submitted") if rejected else (None, "staff_approved")
    )
    audits = list(await db_session.scalars(select(AuditLogModel).where(
        AuditLogModel.entity_id == str(submission_id),
        AuditLogModel.action == "passport_staff_approved",
    )))
    if rejected:
        assert result is None and audits == []
        qr.assert_not_awaited()
    else:
        assert result is not None and result.approved_count == 1
        assert len(audits) == 1
        qr.assert_awaited_once()
