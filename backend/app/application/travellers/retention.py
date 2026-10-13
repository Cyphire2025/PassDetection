"""Independent retained ownership and explicit withdrawal, without age extension."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.data_exports import invalidate_company_exports
from app.application.travellers.snapshot_access import retained_asset_authority
from app.domain.exceptions.exceptions import ValidationError
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel,
    TravellerDocumentAssetModel,
    TravellerDocumentRevisionModel,
    TravellerParticipationModel,
    TravellerProfileModel,
)


async def deletable_storage_keys(
    session: AsyncSession, keys: Sequence[str], *, agency_id: uuid.UUID | None,
) -> list[str]:
    """O(k log assets), k bounded by the existing cleanup batch (2,000 keys).

Retention is checked against records, not a permanent namespace exemption.
Withdrawal removes future-reuse authority. Existing lawful trip snapshots have
independent operational authority until they are deleted; hard erase does not.
"""
    if not any(key.startswith("travellers/") for key in keys):
        return list(keys)
    query = select(TravellerDocumentAssetModel.object_key).join(TravellerProfileModel,
        (TravellerProfileModel.id == TravellerDocumentAssetModel.traveller_id)
        & (TravellerProfileModel.agency_id == TravellerDocumentAssetModel.agency_id)
        & (TravellerProfileModel.company_id == TravellerDocumentAssetModel.company_id),
    ).where(TravellerDocumentAssetModel.object_key.in_(keys),
        TravellerDocumentAssetModel.availability.in_(("pending", "available", "unreadable")),
        TravellerDocumentAssetModel.retention_basis.is_not(None),
        retained_asset_authority(),
    )
    if agency_id is not None:
        query = query.where(TravellerDocumentAssetModel.agency_id == agency_id)
    protected = set((await session.scalars(query)).all())
    return [key for key in keys if key not in protected]


async def detach_submission_provenance(
    session: AsyncSession, submission_ids: Sequence[uuid.UUID],
) -> None:
    """Detach operational-source pointers; immutable source_provenance survives.

Caller must exclude pending asset copies before deleting original source files.
This never deletes independently owned originals or completed-trip snapshots.
"""
    if not submission_ids:
        return
    pending = await session.scalar(select(TravellerDocumentAssetModel.id).join(
        TravellerDocumentRevisionModel,
        TravellerDocumentRevisionModel.id == TravellerDocumentAssetModel.document_revision_id,
    ).where(TravellerDocumentRevisionModel.source_submission_id.in_(submission_ids),
            TravellerDocumentAssetModel.availability == "pending").limit(1))
    if pending is not None:
        raise ValidationError("Retained document copies are still processing. Retry deletion after copying finishes.", field="submission_id")
    await session.execute(update(TravellerDocumentRevisionModel).where(
        TravellerDocumentRevisionModel.source_submission_id.in_(submission_ids),
    ).values(source_submission_id=None, source_group_id=None))
    await session.execute(update(TravellerParticipationModel).where(
        TravellerParticipationModel.source_submission_id.in_(submission_ids),
    ).values(source_submission_id=None))


async def revoke_retained_profile(
    session: AsyncSession, *, agency_id: uuid.UUID, company_id: uuid.UUID,
    traveller_id: uuid.UUID, expected_revision: int,
) -> bool:
    """Immediate access revocation; worker performs bounded physical deletion."""
    person = await session.scalar(select(TravellerProfileModel).where(
        TravellerProfileModel.id == traveller_id, TravellerProfileModel.agency_id == agency_id,
        TravellerProfileModel.company_id == company_id,
    ).with_for_update())
    if person is None or person.revision != expected_revision:
        return False
    person.reuse_permission_status = "withdrawn"
    await invalidate_company_exports(session, agency_id, company_id)
    person.authorization_version += 1
    person.revision += 1
    person.retention_until = datetime.now(UTC)
    session.add(TravellerChangeEventModel(agency_id=agency_id, company_id=company_id,
        traveller_id=traveller_id, event_type="reuse_revoked", aggregate_id=traveller_id,
        aggregate_revision=person.revision, idempotency_key=f"withdraw:{traveller_id}:{person.revision}",
        reason_code="explicit_reuse_withdrawal"))
    return True
