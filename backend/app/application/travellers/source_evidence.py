"""Stable private binding of an uploaded candidate to reviewed source content."""

import json

from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


def source_evidence_digest(crypto: TravellerReuseCrypto, source: PassportSubmissionModel) -> str:
    # Staff approval increments its row revision even when nothing changed.
    # Content binding permits that transition but never ignores edited evidence.
    content = {"fields": source.confirmed_fields, "images": [source.image_s3_key,
        source.passport_back_s3_key, source.passport_cover_s3_key, source.passport_back_cover_s3_key,
        source.passport_photo_s3_key]}
    return crypto.scoped_digest("replacement-source", source.agency_id, source.group_id,
        str(source.id), json.dumps(content, sort_keys=True, separators=(",", ":")))
