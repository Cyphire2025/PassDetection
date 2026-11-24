"""Real ORM office routes with synthetic data and isolated upload-stage controls."""

from __future__ import annotations

import uuid
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select, update

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DocumentDistributionBatchModel,
    PassportSubmissionModel,
    UserModel,
)
from app.presentation.api.v1.routes import (
    document_distribution_reupload as reupload,
)
from app.presentation.api.v1.routes import (
    document_distribution_save as save,
)


async def context(session, *, batch_status="draft"):
    agency = AgencyModel(name="Synthetic document agency", email=f"{uuid.uuid4()}@example.test")
    session.add(agency)
    await session.flush()
    actor = User.create(
        email=f"{uuid.uuid4()}@example.test",
        hashed_password="unused",
        full_name="Synthetic operator",
        role=UserRole.AGENCY_ADMIN,
        agency_id=agency.id,
    )
    session.add(
        UserModel(
            id=actor.id,
            agency_id=agency.id,
            email=actor.email,
            hashed_password="unused",
            full_name=actor.full_name,
            role=actor.role.value,
        )
    )
    await session.flush()
    group = ClientGroupModel(
        agency_id=agency.id,
        created_by_user_id=actor.id,
        name="Synthetic document trip",
        token=uuid.uuid4().hex,
    )
    session.add(group)
    await session.flush()
    passenger = PassportSubmissionModel(
        agency_id=agency.id,
        group_id=group.id,
        client_name="Synthetic passenger",
        image_s3_key="synthetic/passport.jpg",
        status="confirmed",
    )
    batch = DocumentDistributionBatchModel(
        agency_id=agency.id,
        group_id=group.id,
        document_type="visa",
        status=batch_status,
        created_by_user_id=actor.id,
    )
    session.add_all([passenger, batch])
    await session.flush()
    return SimpleNamespace(
        actor=actor,
        agency_id=agency.id,
        group_id=group.id,
        passenger_id=passenger.id,
        batch_id=batch.id,
        batch=batch,
    )


class BoundedReadReached(RuntimeError):
    pass


async def test_reupload_reaches_bounded_validation_after_actual_orm_rollback(
    db_session, monkeypatch
):
    ctx = await context(db_session)
    read = AsyncMock(side_effect=BoundedReadReached("synthetic bounded-read boundary"))
    monkeypatch.setattr(reupload, "read_bounded_document_uploads", read)
    with pytest.raises(BoundedReadReached, match="synthetic bounded-read boundary"):
        await reupload.reupload_passenger_document(
            group_id=ctx.group_id,
            document_type="visa",
            passenger_id=ctx.passenger_id,
            file=UploadFile(file=BytesIO(b"not parsed"), filename="synthetic.pdf"),
            current_user=ctx.actor,
            session=db_session,
        )
    read.assert_awaited_once()
    assert read.await_args.kwargs["security_context"].agency_id == ctx.agency_id


@pytest.mark.parametrize("cached_status", ["draft", "saved"])
async def test_save_refuses_processing_status_changed_after_initial_lookup(
    db_session,
    monkeypatch,
    cached_status,
):
    ctx = await context(db_session, batch_status=cached_status)
    authorize = save._get_authorized_group
    observed = []

    async def transition_after_authorization(*args, **kwargs):
        group = await authorize(*args, **kwargs)
        # A real SQL update leaves the already-loaded ORM object's cached value
        # unchanged, reproducing the normal read→locked-read identity-map gap.
        await db_session.execute(
            update(DocumentDistributionBatchModel)
            .where(DocumentDistributionBatchModel.id == ctx.batch_id)
            .values(status="processing")
            .execution_options(synchronize_session=False)
        )
        observed.append(
            await db_session.scalar(
                select(DocumentDistributionBatchModel.status).where(
                    DocumentDistributionBatchModel.id == ctx.batch_id
                )
            )
        )
        assert ctx.batch.status == cached_status
        return group

    monkeypatch.setattr(save, "_get_authorized_group", transition_after_authorization)
    with pytest.raises(HTTPException) as error:
        await save.save_document_lane(
            batch_id=ctx.batch_id, current_user=ctx.actor, session=db_session
        )
    assert error.value.status_code == 409
    assert "upload to finish" in error.value.detail
    assert observed == ["processing"]
    assert (
        await db_session.scalar(
            select(DocumentDistributionBatchModel.status).where(
                DocumentDistributionBatchModel.id == ctx.batch_id
            )
        )
        == "processing"
    )


@pytest.mark.parametrize("status", ["draft", "saved", "processing"])
async def test_save_preserves_normal_draft_saved_and_processing_outcomes(db_session, status):
    ctx = await context(db_session, batch_status=status)
    if status == "processing":
        with pytest.raises(HTTPException) as error:
            await save.save_batch(batch_id=ctx.batch_id, current_user=ctx.actor, session=db_session)
        assert error.value.status_code == 409
    else:
        result = await save.save_batch(
            batch_id=ctx.batch_id, current_user=ctx.actor, session=db_session
        )
        assert result.batch_id == ctx.batch_id and result.status == "saved"


async def test_save_keeps_foreign_agency_batch_unavailable(db_session):
    ctx = await context(db_session)
    foreign = User.create(
        email="foreign-synthetic@example.test",
        hashed_password="unused",
        full_name="Foreign operator",
        role=UserRole.AGENCY_ADMIN,
        agency_id=uuid.uuid4(),
    )
    with pytest.raises(HTTPException) as error:
        await save.save_document_lane(
            batch_id=ctx.batch_id, current_user=foreign, session=db_session
        )
    assert error.value.status_code == 404
    assert ctx.batch.status == "draft"
