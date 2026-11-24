"""Lock an existing reuse snapshot without reopening historical or reviewed trips."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.history import ReviewContext
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import TravellerParticipationModel
from app.infrastructure.repositories.coordinator_assignment_lifecycle import current_trip_clause


class ExistingReuseSource(NamedTuple):
    source: PassportSubmissionModel | None
    refresh_current_phone: bool
    keep_operational_acceptance: bool


async def locked_reuse_source(
    session: AsyncSession,
    context: ReviewContext,
    participation: TravellerParticipationModel,
    revision_id: uuid.UUID,
    now: datetime,
) -> ExistingReuseSource:
    """Use the same parent transaction and row lock; never flush or commit."""
    grant, scope, _, _, _, _ = context
    source = None
    refresh_current_phone = False
    if participation.source_submission_id:
        source_row = (
            await session.execute(
                select(PassportSubmissionModel, current_trip_clause(now, group_model=scope.group))
                .where(
                    PassportSubmissionModel.id == participation.source_submission_id,
                    PassportSubmissionModel.group_id == grant.group_id,
                    PassportSubmissionModel.agency_id == grant.agency_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if source_row is not None:
            source, refresh_current_phone = source_row
            if not refresh_current_phone:
                # Prior trips are immutable snapshots, including their answers.
                raise ReuseError(ReuseReason.REVISION_CONFLICT)
        if source is not None and (source.staff_metadata or {}).get(
            "reuse_document_revision_id"
        ) != str(revision_id):
            # An independently uploaded/approved submission must stay in its
            # original review workflow, never be silently rewritten by reuse.
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
        if source is not None and (
            source.status not in {"confirmed", "client_submitted"}
            or (source.staff_metadata or {}).get("reuse_assignment")
            not in {"automatic", "traveller"}
            or source.verification_reviewed_at is not None
            or source.post_submission_verified_at is not None
            or source.post_submission_verification is not None
        ):
            # A reviewed or newly updated document belongs to its verification
            # workflow. The unchanged-history endpoint cannot reset that state.
            raise ReuseError(ReuseReason.REVISION_CONFLICT)
    keep_operational_acceptance = (
        participation.status == "accepted"
        and source is not None
        and (source.staff_metadata or {}).get("reuse_assignment") == "automatic"
    )
    return ExistingReuseSource(source, refresh_current_phone, keep_operational_acceptance)
