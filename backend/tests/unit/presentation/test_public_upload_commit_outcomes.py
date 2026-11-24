"""Real public draft commits remain recoverable after a lost acknowledgement."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.use_cases.passports.reconcile_passport_upload_use_case import (
    ReconcilePassportUploadUseCase,
)
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.routes.passport_routes import public_upload
from tests.passport_image_mutations import seed_image_mutation_context
from tests.route_dependencies import set_route_dependency


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["acknowledged", "rejected", "acknowledgement_lost"])
async def test_details_only_upload_commit_and_recovery_use_the_same_durable_attempt(
    db_session, monkeypatch, outcome
):
    context = await seed_image_mutation_context(db_session)
    group_id = context.submission.group_id
    await db_session.execute(
        update(ClientGroupModel).where(ClientGroupModel.id == group_id)
        .values(upload_configuration={"passport_enabled": False})
    )
    await db_session.commit()
    group = await ClientGroupRepository(db_session).get_by_id(group_id)
    assert group is not None
    token = group.token
    credential = "synthetic-upload-attempt-" + "a" * 40
    storage = AsyncMock()
    use_case = SubmitPassportUseCase(
        ClientGroupRepository(db_session), PassportSubmissionRepository(db_session), storage
    )
    original_commit = db_session.commit

    async def commit():
        if outcome == "rejected":
            raise ConnectionError("synthetic commit rejected")
        await original_commit()
        if outcome == "acknowledgement_lost":
            raise ConnectionError("synthetic commit acknowledgement lost")

    async def serialize(result, **_kwargs):
        return result

    events = []
    # The test driver's legacy SQLite transaction mode does not BEGIN on
    # SELECT. Establish a real outer transaction before the repository's
    # idempotency savepoint so rollback has production-like semantics.
    await db_session.execute(text("BEGIN"))
    monkeypatch.setattr(db_session, "commit", commit)
    set_route_dependency(monkeypatch, public_upload, "_response_from_dto", serialize)
    set_route_dependency(
        monkeypatch, public_upload, "propagate_mobile_passenger_change", AsyncMock()
    )
    set_route_dependency(
        monkeypatch, public_upload, "record_operational_event",
        lambda event, reason: events.append(reason),
    )
    call = public_upload.upload_passport(
        token, BackgroundTasks(), client_name="Synthetic Traveller", acquisition_mode="file",
        upload_idempotency_key=credential, upload_session_id=credential,
        qualifier_selection_token=None, file=None, passport_back_file=None,
        passport_photo_file=None, passport_cover_file=None, passport_back_cover_file=None,
        visa_photo_source=None, use_case=use_case, session=db_session,
    )
    result = None
    if outcome == "acknowledged":
        result = await call
        assert events == ["success"]
    else:
        with pytest.raises(HTTPException) as error:
            await call
        assert error.value.status_code == 503
        assert events == ["database_failed"]

    # A separate session observes the actual database outcome after rollback,
    # through the same recovery use case used by the public reconciliation API.
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as observer:
        recovery = ReconcilePassportUploadUseCase(
            ClientGroupRepository(observer), PassportSubmissionRepository(observer)
        )
        recovered_id = await recovery.execute(token=token, upload_idempotency_key=credential)
        persisted = await PassportSubmissionRepository(observer).get_by_upload_idempotency_key(
            group_id, credential
        )
        if outcome == "rejected":
            assert recovered_id is None and persisted is None
        else:
            assert persisted is not None and persisted.id == recovered_id
            assert persisted.image_s3_key == ""
            if result is not None:
                assert result.id == recovered_id
    storage.upload_file.assert_not_awaited()
    storage.delete_files.assert_not_awaited()
