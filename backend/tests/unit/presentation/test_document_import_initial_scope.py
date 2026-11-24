"""Initial export policy still denies before native work and handles empty matches."""

import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import update

from app.infrastructure.database.models import UserModel
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.passport_routes import document_import as route
from tests.unit.presentation.document_import_authority_fixture import (
    perform_held_import,
    persist_authority_transition,
    prepare_authority_import,
)


@pytest.mark.parametrize(
    "condition,status",
    [
        ("no_agency", 403),
        ("coordinator", 403),
        ("missing_group", 404),
        ("assignment_revoked", 403),
        ("group_deleted", 403),
        ("no_files", 400),
    ],
)
async def test_initial_policy_rejects_before_native_validation(
    db_session,
    monkeypatch,
    test_settings,
    condition,
    status,
):
    context = await prepare_authority_import(
        db_session,
        monkeypatch,
        test_settings,
        condition,
        "validation",
    )
    actor = context.actor
    if condition in {"no_agency", "coordinator"}:
        values = {"agency_id": None} if condition == "no_agency" else {"role": "agency_coordinator"}
        await db_session.execute(update(UserModel).where(UserModel.id == actor.id).values(**values))
        await db_session.commit()
        actor = await UserRepository(db_session).get_by_id(actor.id)
    elif condition in {"assignment_revoked", "group_deleted"}:
        await persist_authority_transition(context)
    file = UploadFile(io.BytesIO(context.payload), filename="STF_A1_FRONT.jpg")
    try:
        with pytest.raises(HTTPException) as failure:
            await route.preview_passport_documents_by_group(
                uuid.uuid4() if condition == "missing_group" else context.group_id,
                files=[] if condition == "no_files" else [file],
                current_user=actor,
                session=db_session,
            )
        assert failure.value.status_code == status
        assert not context.barrier.entered.is_set() and context.objects == {}
    finally:
        await file.close()


@pytest.mark.parametrize("transition", ["unchanged", "sessions_revoked"])
async def test_save_with_no_matching_documents_rechecks_actor_before_zero_save_response(
    db_session,
    monkeypatch,
    test_settings,
    transition,
):
    context = await prepare_authority_import(
        db_session,
        monkeypatch,
        test_settings,
        transition,
        "validation",
    )
    context.filename = "not-a-staff-document.jpg"
    result = await perform_held_import(context, db_session, "save_validation")
    if transition == "sessions_revoked":
        assert isinstance(result, HTTPException) and result.status_code == 403
    else:
        assert not isinstance(result, BaseException), repr(result)
        assert result.saved_count == result.accepted_count == 0 and result.rejected_count == 1
    assert context.objects == {}
