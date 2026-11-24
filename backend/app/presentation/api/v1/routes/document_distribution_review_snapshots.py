"""Deterministic linked-source and passenger matching snapshots."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)


@dataclass(frozen=True)
class _LinkedDocumentMatchSource:
    """A canonical view of every linked row that can influence assignment."""

    linked_broadcasts: dict[uuid.UUID, str]
    recipients: tuple[WhatsAppBroadcastRecipientModel, ...]
    snapshot: tuple[tuple[str, ...], ...]


def _snapshot_value(value: object) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _linked_document_match_source_from_models(
    *,
    group: ClientGroupModel,
    links: list[ClientGroupWhatsAppBroadcastLinkModel],
    broadcasts: list[WhatsAppBroadcastGroupModel],
    recipients: list[WhatsAppBroadcastRecipientModel],
) -> _LinkedDocumentMatchSource:
    """Build a deterministic, tenant-scoped snapshot from one coherent row set."""

    linked_broadcasts = {
        broadcast.id: broadcast.name
        for broadcast in broadcasts
        if broadcast.agency_id == group.agency_id
    }
    scoped_links = sorted(
        (
            link
            for link in links
            if link.agency_id == group.agency_id
            and link.client_group_id == group.id
            and link.broadcast_group_id in linked_broadcasts
        ),
        key=lambda item: str(item.id),
    )
    scoped_recipients = sorted(
        (
            recipient
            for recipient in recipients
            if recipient.agency_id == group.agency_id
            and recipient.broadcast_group_id in linked_broadcasts
            and recipient.removed_at is None
        ),
        key=lambda item: str(item.id),
    )
    snapshot: list[tuple[str, ...]] = []
    for link in scoped_links:
        snapshot.append(
            (
                "link",
                str(link.id),
                str(link.client_group_id),
                str(link.broadcast_group_id),
                str(link.agency_id),
                str(link.created_by_user_id or ""),
                _snapshot_value(link.created_at),
            )
        )
    for broadcast in sorted(broadcasts, key=lambda item: str(item.id)):
        if broadcast.id not in linked_broadcasts:
            continue
        snapshot.append(
            (
                "broadcast",
                str(broadcast.id),
                str(broadcast.agency_id),
                str(broadcast.name or ""),
            )
        )
    for recipient in scoped_recipients:
        snapshot.append(
            (
                "recipient",
                str(recipient.id),
                str(recipient.broadcast_group_id),
                str(recipient.agency_id),
                str(recipient.name or ""),
                str(recipient.normalized_phone_number or ""),
                _snapshot_value(recipient.created_at),
                json.dumps(
                    dict(recipient.imported_fields or {}),
                    sort_keys=True,
                    default=str,
                    separators=(",", ":"),
                ),
            )
        )
    return _LinkedDocumentMatchSource(
        linked_broadcasts=linked_broadcasts,
        recipients=tuple(scoped_recipients),
        snapshot=tuple(snapshot),
    )


def _document_match_roster_snapshot(
    passengers: list[PassportSubmission],
) -> tuple[tuple[str, ...], ...]:
    """Capture every passenger field that can influence document assignment."""

    snapshots: list[tuple[str, ...]] = []
    for passenger in passengers:
        updated_at: object = getattr(passenger, "updated_at", None)
        updated_at_snapshot = (
            updated_at.isoformat() if isinstance(updated_at, (date, datetime)) else str(updated_at)
        )
        snapshots.append(
            (
                str(passenger.id),
                updated_at_snapshot,
                str(getattr(passenger, "client_name", "") or ""),
                str(getattr(passenger, "display_name", "") or ""),
                str(getattr(passenger, "client_phone", "") or ""),
                str(getattr(passenger, "family_head_phone", "") or ""),
                json.dumps(
                    {
                        "confirmed_fields": getattr(passenger, "confirmed_fields", None) or {},
                        "extracted_fields": getattr(passenger, "extracted_fields", None) or {},
                        "staff_metadata": getattr(passenger, "staff_metadata", None) or {},
                        "custom_answers": getattr(passenger, "custom_answers", None) or [],
                        "custom_detail_answers": (
                            getattr(passenger, "custom_detail_answers", None) or []
                        ),
                    },
                    sort_keys=True,
                    default=str,
                    separators=(",", ":"),
                ),
            )
        )
    return tuple(sorted(snapshots))


_LinkedDocumentMatchSource.__module__ = (
    "app.presentation.api.v1.routes.document_distribution_review_support"
)
_snapshot_value.__module__ = "app.presentation.api.v1.routes.document_distribution_review_support"
_linked_document_match_source_from_models.__module__ = (
    "app.presentation.api.v1.routes.document_distribution_review_support"
)
_document_match_roster_snapshot.__module__ = (
    "app.presentation.api.v1.routes.document_distribution_review_support"
)

for _method_name in ("__init__", "__repr__", "__eq__", "__setattr__", "__delattr__", "__hash__"):
    getattr(
        _LinkedDocumentMatchSource, _method_name
    ).__module__ = "app.presentation.api.v1.routes.document_distribution_review_support"
del _method_name
