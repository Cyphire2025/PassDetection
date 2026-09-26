"""Behavioral constraint tests shared by SQLite and migrated PostgreSQL."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
)
from tests.persistence import persist_graph

CASES = (
    "passport_wrong_agency", "batch_unknown_state", "item_unknown_state", "item_unknown_result",
    "negative_input_tokens", "negative_output_tokens", "negative_attempts",
    "completed_missing_result", "queued_with_result", "failed_with_result",
)


async def assert_data_invariant(session: AsyncSession, case: str) -> None:
    agency, other, group, batch, control = (uuid.uuid4() for _ in range(5))
    await persist_graph(session, [
        AgencyModel(id=agency, name="Synthetic owner", email=f"{agency}@example.test"),
        AgencyModel(id=other, name="Synthetic other", email=f"{other}@example.test"),
        ClientGroupModel(id=group, agency_id=agency, name="Synthetic group",
                         token=f"synthetic-{group}", status="active"),
        EcrBatchModel(id=batch, agency_id=agency, title="Synthetic batch", expected_count=1),
    ])

    def passport(identifier: uuid.UUID, tenant: uuid.UUID) -> PassportSubmissionModel:
        return PassportSubmissionModel(id=identifier, agency_id=tenant, group_id=group,
                                       client_name="Synthetic traveller", image_s3_key="synthetic")

    def item(**changes: object) -> EcrItemModel:
        fields = dict(id=uuid.uuid4(), batch_id=batch, client_id=uuid.uuid4(),
                      original_filename="synthetic.jpg", content_type="image/jpeg", sha256="0" * 64,
                      status="queued", result=None, attempts=0, input_tokens=0, output_tokens=0)
        fields.update(changes)
        return EcrItemModel(**fields)

    session.add(passport(control, agency))
    # All legitimate persistent states and retry transitions must remain legal.
    for status, result in (("queued", None), ("processing", None), ("failed", None),
                           ("completed", "ECR"), ("completed", "NA"),
                           ("completed", "NEEDS_REVIEW")):
        session.add(item(status=status, result=result, attempts=2))
    retry = item(status="failed", attempts=3)
    session.add(retry)
    await session.flush()
    retry.status = "queued"
    await session.flush()

    invalid: object
    if case == "passport_wrong_agency":
        invalid = passport(uuid.uuid4(), other)
    elif case == "batch_unknown_state":
        invalid = EcrBatchModel(agency_id=agency, title="Invalid state", expected_count=1,
                                status="unknown")
    else:
        invalid = item(**{
            "item_unknown_state": {"status": "unknown"},
            "item_unknown_result": {"status": "completed", "result": "unknown"},
            "negative_input_tokens": {"input_tokens": -1},
            "negative_output_tokens": {"output_tokens": -1},
            "negative_attempts": {"attempts": -1},
            "completed_missing_result": {"status": "completed"},
            "queued_with_result": {"result": "ECR"},
            "failed_with_result": {"status": "failed", "result": "NA"},
        }[case])
    with pytest.raises(IntegrityError) as failure:
        async with session.begin_nested():
            session.add(invalid)
            await session.flush()
    expected = "23503" if case == "passport_wrong_agency" else "23514"
    if session.get_bind().dialect.name == "postgresql":
        assert getattr(failure.value.orig, "sqlstate", None) == expected
    else:
        assert getattr(failure.value.orig, "sqlite_errorname", None) == (
            "SQLITE_CONSTRAINT_FOREIGNKEY" if case == "passport_wrong_agency"
            else "SQLITE_CONSTRAINT_CHECK"
        )
    assert await session.scalar(select(PassportSubmissionModel.id).where(
        PassportSubmissionModel.id == control)) == control
    await session.refresh(retry)
    assert retry.status == "queued" and retry.attempts == 3
