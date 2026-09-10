"""Frozen per-link matching policy helpers for document distribution."""

from __future__ import annotations

import uuid

from app.infrastructure.database.models import ClientGroupWhatsAppBroadcastLinkModel
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    matching_field_keys_from_storage,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _LinkedDocumentMatchSource,
)


def source_matching_fields_by_broadcast(
    source: _LinkedDocumentMatchSource,
) -> dict[uuid.UUID, tuple[str, ...] | None]:
    """Recover the per-link policy captured in this source's frozen snapshot."""

    matching_fields: dict[uuid.UUID, tuple[str, ...] | None] = {}
    for row in source.snapshot:
        if len(row) < 4 or row[0] != "link_matching_fields":
            continue
        try:
            broadcast_id = uuid.UUID(row[2])
        except ValueError:
            continue
        matching_fields[broadcast_id] = None if row[3] == "legacy" else tuple(row[4:])
    return matching_fields


def source_with_matching_fields(
    source: _LinkedDocumentMatchSource,
    links: list[ClientGroupWhatsAppBroadcastLinkModel],
) -> _LinkedDocumentMatchSource:
    """Fence matching-policy changes together with the existing link snapshot."""

    policy_snapshot = tuple(
        (
            "link_matching_fields",
            str(link.id),
            str(link.broadcast_group_id),
            (
                "legacy"
                if matching_field_keys_from_storage(
                    getattr(link, "matching_field_keys", None),
                )
                is None
                else "configured"
            ),
            *(
                matching_field_keys_from_storage(
                    getattr(link, "matching_field_keys", None),
                )
                or ()
            ),
        )
        for link in sorted(links, key=lambda item: str(item.id))
    )
    return _LinkedDocumentMatchSource(
        linked_broadcasts=source.linked_broadcasts,
        recipients=source.recipients,
        snapshot=(*source.snapshot, *policy_snapshot),
    )
