"""Deletion protects scoped roster references without emitting corrupt payloads."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
)
from app.presentation.api.v1.routes.passport_routes import bulk_actions, export_context
from tests.passport_image_mutations import seed_image_mutation_context


@pytest.mark.asyncio
async def test_roster_delete_guard_keeps_active_references_only_in_selected_group(db_session):
    context = await seed_image_mutation_context(db_session)
    source = context.submission
    excluded, restored, foreign = (uuid.uuid4() for _ in range(3))
    other = ClientGroupModel(agency_id=source.agency_id, created_by_user_id=context.actor.id,
                             token=uuid.uuid4().hex, name="Other synthetic group")
    db_session.add(other)
    await db_session.flush()
    other_source = PassportSubmissionModel(agency_id=source.agency_id, group_id=other.id,
                                           client_name="Other", image_s3_key="front/other.jpg")
    db_session.add(other_source)
    await db_session.flush()
    db_session.add_all([
        PassportRosterResolutionModel(agency_id=source.agency_id, client_group_id=source.group_id,
            submission_id=source.id, resolution_type="rejected", excluded_submission_ids=[str(excluded)]),
        PassportRosterResolutionModel(agency_id=source.agency_id, client_group_id=source.group_id,
            submission_id=source.id, resolution_type="rejected", status="restored",
            restored_at=datetime.now(UTC), excluded_submission_ids=[str(restored)]),
        PassportRosterResolutionModel(agency_id=source.agency_id, client_group_id=other.id,
            submission_id=other_source.id, resolution_type="rejected", excluded_submission_ids=[str(foreign)]),
    ])
    await db_session.flush()
    assert await bulk_actions._active_roster_resolution_references(
        db_session, group_id=source.group_id, agency_id=source.agency_id
    ) == {source.id, excluded}
    assert await bulk_actions._active_roster_resolution_references(
        db_session, group_id=source.group_id, agency_id=uuid.uuid4()
    ) == set()


@pytest.mark.asyncio
async def test_corrupt_roster_diagnostic_contains_type_and_resolution_id_only(db_session, monkeypatch):
    context = await seed_image_mutation_context(db_session)
    marker = "synthetic-private-passenger-reference"
    resolution = PassportRosterResolutionModel(
        agency_id=context.submission.agency_id, client_group_id=context.submission.group_id,
        submission_id=context.submission.id, resolution_type="rejected",
        excluded_submission_ids=[marker],
    )
    db_session.add(resolution)
    await db_session.flush()
    warning = Mock()
    monkeypatch.setattr(bulk_actions.logger, "warning", warning)
    with pytest.raises(HTTPException) as error:
        await bulk_actions._active_roster_resolution_references(
            db_session, group_id=context.submission.group_id, agency_id=context.submission.agency_id
        )
    assert error.value.status_code == 409 and "integrity check" in error.value.detail
    assert marker not in repr(warning.call_args)
    assert warning.call_args.kwargs["resolution_id"] == str(resolution.id)
    assert warning.call_args.kwargs["value_type"] == "str"


@pytest.mark.asyncio
async def test_export_corrupt_roster_diagnostic_keeps_existing_skip_behavior(monkeypatch):
    marker = "synthetic-private-export-reference"
    source = SimpleNamespace(id=uuid.uuid4())
    resolution = SimpleNamespace(id=uuid.uuid4(), submission_id=source.id,
                                 resolution_type="replacement", excluded_submission_ids=[marker])
    rows = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [resolution]))
    session = SimpleNamespace(execute=AsyncMock(return_value=rows))
    warning = Mock()
    monkeypatch.setattr(export_context.logger, "warning", warning)
    assert await export_context._without_rejected_roster_submissions(
        session, [source], group_id=uuid.uuid4(), agency_id=uuid.uuid4()
    ) == [source]
    assert marker not in repr(warning.call_args)
    assert warning.call_args.kwargs["resolution_id"] == str(resolution.id)
    assert warning.call_args.kwargs["value_type"] == "str"
