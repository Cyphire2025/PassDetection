"""Authority for independent copies between immutable versions of one person."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.asset_policy import is_reviewable_asset
from app.application.travellers.retained_authority import has_retained_authority
from app.domain.services.traveller_verification import utc
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel as Asset,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel as Document,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerProfileModel as Person,
)


async def has_staff_copy_authority(session: AsyncSession, asset: Asset, now: datetime) -> bool:
    row = (await session.execute(select(Document, Person).join(Person,
        (Person.id == Document.traveller_id) & (Person.agency_id == Document.agency_id)
        & (Person.company_id == Document.company_id)).where(Document.id == asset.document_revision_id,
            Document.agency_id == asset.agency_id, Document.company_id == asset.company_id,
            Document.traveller_id == asset.traveller_id, Document.passport_id == asset.passport_id))).first()
    if row is None:
        return False
    revision, person = row
    try:
        parent_id = uuid.UUID(str(revision.source_provenance.get("copy_parent_revision_id", "")))
    except ValueError:
        return False
    if (not revision.source_provenance.get("staff_record_edit") or revision.status != "accepted"
            or revision.accepted_by_user_id is None or not has_retained_authority(person)
            or not asset.source_object_key or not asset.object_key or not asset.retention_basis
            or asset.purged_at is not None or (asset.retention_until is not None and utc(asset.retention_until) <= now)
            or (person.retention_until is not None and utc(person.retention_until) <= now)):
        return False
    parent = await session.scalar(select(Asset).where(Asset.agency_id == asset.agency_id,
        Asset.company_id == asset.company_id, Asset.traveller_id == asset.traveller_id,
        Asset.document_revision_id == parent_id, Asset.object_key == asset.source_object_key,
        Asset.document_side == asset.document_side, Asset.kind == "original").limit(1))
    return bool(parent and is_reviewable_asset(parent, now))
