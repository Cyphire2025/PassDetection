"""One availability rule for review, private delivery, and reuse publication."""

from datetime import datetime

from app.domain.services.traveller_verification import utc
from app.infrastructure.database.traveller_reuse_models import TravellerDocumentAssetModel

MAX_PRIVATE_DOCUMENT_BYTES = 20 * 1024 * 1024
PRIVATE_DOCUMENT_SUFFIXES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}
PRIVATE_DOCUMENT_TYPES = frozenset(PRIVATE_DOCUMENT_SUFFIXES)


def is_reviewable_asset(asset: TravellerDocumentAssetModel, now: datetime) -> bool:
    return bool(
        asset.availability == "available" and asset.purged_at is None
        and asset.object_key and asset.retention_basis
        and 1 <= asset.byte_size <= MAX_PRIVATE_DOCUMENT_BYTES
        and asset.content_type in PRIVATE_DOCUMENT_TYPES
        and (asset.retention_until is None or utc(asset.retention_until) > now)
    )
