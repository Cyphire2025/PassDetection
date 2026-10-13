"""One immutable-document snapshot constructor for public and operator reuse."""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from app.application.travellers.asset_policy import is_reviewable_asset
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel,
    TravellerDocumentRevisionModel,
    TravellerProfileModel,
)


def new_reuse_submission(*, group: ClientGroupModel, person: TravellerProfileModel,
    revision: TravellerDocumentRevisionModel, assets: Sequence[TravellerDocumentAssetModel],
    fields: dict[str, str], display_name: str, phone: str | None, email: str | None,
    participation_id: uuid.UUID, now: datetime, traveller_confirmed: bool,
) -> PassportSubmissionModel:
    keys = {asset.document_side: asset.object_key for asset in assets if is_reviewable_asset(asset, now)}
    return PassportSubmissionModel(
        id=uuid.uuid4(), agency_id=group.agency_id, group_id=group.id,
        client_name=display_name, client_email=email, client_phone=phone,
        image_s3_key=keys.get("front") or "", passport_back_s3_key=keys.get("back"),
        passport_cover_s3_key=keys.get("cover"), passport_back_cover_s3_key=keys.get("back_cover"),
        passport_photo_s3_key=keys.get("photo"), acquisition_mode="file",
        upload_idempotency_key=f"reuse:{participation_id}",
        status="client_submitted" if traveller_confirmed else "confirmed",
        extraction_status="extraction_complete", extraction_revision=1,
        extracted_fields=fields, confirmed_fields=fields,
        client_reviewed_at=now if traveller_confirmed else None,
        staff_metadata={"reuse_traveller_id": str(person.id), "reuse_document_revision_id": str(revision.id),
                        "reuse_assignment": "traveller" if traveller_confirmed else "automatic"},
    )
