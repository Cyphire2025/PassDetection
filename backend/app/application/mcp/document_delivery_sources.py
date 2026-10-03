"""Exact saved source binding; metadata digests never claim file-byte integrity."""

from __future__ import annotations

import hashlib
from typing import Any

from app.application.mcp.credentials import utc
from app.infrastructure.database.models import DistributedDocumentModel


def document_source(document: DistributedDocumentModel) -> dict[str, Any]:
    return {
        "id": str(document.id), "agency_id": str(document.agency_id),
        "group_id": str(document.group_id), "batch_id": str(document.batch_id),
        "passenger_id": str(document.passenger_id), "document_type": document.document_type,
        "filename": document.original_filename, "media_type": document.content_type,
        "storage_reference_digest": hashlib.sha256(document.storage_key.encode()).hexdigest(),
        "revision": utc(document.updated_at).isoformat(), "match_status": document.match_status,
    }
