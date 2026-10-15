"""Build a fresh, explicit audience for a text-only document update."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.document_updates import (
    ACCEPTED,
    ACTIVE,
    needs_document_update,
)
from app.core.config.settings import get_settings
from app.infrastructure.database.models import (
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.whatsapp.template_settings import (
    configured_template_name,
    template_language,
)
from app.infrastructure.whatsapp.traveller_destinations import load_traveller_destinations
from app.presentation.api.v1.schemas.document_update_schemas import (
    DocumentUpdatePreview,
    DocumentUpdateRecipient,
)


def fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


async def build_update_preview(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    document_type: str,
    broadcast_group_id: uuid.UUID | None = None,
    lock: bool = False,
) -> DocumentUpdatePreview:
    destinations = await load_traveller_destinations(
        session,
        agency_id=group.agency_id,
        group_id=group.id,
        lock=lock,
    )
    # Office labels affect this preview only. Destination resolution above keeps
    # using original contact/passport identities, so an alias cannot reroute it.
    display_names: dict[uuid.UUID, str] = {}
    destination_ids = [destination.passenger_id for destination in destinations]
    for offset in range(0, len(destination_ids), 500):
        labels = await session.execute(
            select(
                PassportSubmissionModel.id,
                PassportSubmissionModel.display_name,
            ).where(
                PassportSubmissionModel.agency_id == group.agency_id,
                PassportSubmissionModel.group_id == group.id,
                PassportSubmissionModel.id.in_(destination_ids[offset : offset + 500]),
                PassportSubmissionModel.display_name.is_not(None),
            )
        )
        display_names.update((identifier, name) for identifier, name in labels if name)
    documents = list(
        (
            await session.scalars(
                select(DistributedDocumentModel).where(
                    DistributedDocumentModel.agency_id == group.agency_id,
                    DistributedDocumentModel.group_id == group.id,
                    DistributedDocumentModel.document_type == document_type,
                    DistributedDocumentModel.passenger_id.is_not(None),
                    DistributedDocumentModel.match_status.not_in(
                        ("duplicate_document", "superseded")
                    ),
                )
            )
        ).all()
    )
    document_ids = {doc.id for doc in documents}
    confirmed_results = (
        set(
            (
                await session.scalars(
                    select(DocumentWhatsAppDeliveryModel.distributed_document_id).where(
                        DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
                        DocumentWhatsAppDeliveryModel.group_id == group.id,
                        DocumentWhatsAppDeliveryModel.distributed_document_id.in_(document_ids),
                        DocumentWhatsAppDeliveryModel.status.in_(ACCEPTED),
                    )
                )
            ).all()
        )
        if document_ids
        else set()
    )
    confirmed = {identifier for identifier in confirmed_results if identifier is not None}
    by_passenger: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for doc in documents:
        if doc.passenger_id is not None:
            by_passenger[doc.passenger_id].add(doc.id)
    updates = await session.stream(
        select(
            WhatsAppMessageLogModel.id,
            WhatsAppMessageLogModel.status,
            WhatsAppMessageLogModel.error_message,
            WhatsAppMessageLogModel.status_updated_at,
            WhatsAppMessageLogModel.document_update_context,
        )
        .where(
            WhatsAppMessageLogModel.agency_id == group.agency_id,
            WhatsAppMessageLogModel.message_type == "document_update",
            WhatsAppMessageLogModel.document_update_context["group_id"].as_string()
            == str(group.id),
            WhatsAppMessageLogModel.document_update_context["document_type"].as_string()
            == document_type,
        )
        .order_by(WhatsAppMessageLogModel.created_at.desc(), WhatsAppMessageLogModel.id.desc())
        .execution_options(yield_per=500)
    )
    latest: dict[str, str] = {}
    latest_receipts: dict[str, str] = {}
    latest_errors: dict[str, str | None] = {}
    latest_times: dict[str, datetime] = {}
    active: set[str] = set()
    async for log_id, log_status, log_error, log_time, context in updates:
        for passenger_id in (context or {}).get("passenger_ids", []):
            latest.setdefault(passenger_id, log_status)
            latest_receipts.setdefault(passenger_id, str(log_id))
            latest_errors.setdefault(
                passenger_id,
                log_error if log_status in {"failed", "delivery_unknown", "skipped"} else None,
            )
            latest_times.setdefault(passenger_id, log_time)
            if log_status in ACTIVE:
                active.add(passenger_id)
    rows = []
    for destination in destinations:
        if broadcast_group_id and destination.broadcast_group_id != broadcast_group_id:
            continue
        ids = by_passenger[destination.passenger_id]
        needs_update = needs_document_update(ids, confirmed)
        reason = None
        if not needs_update:
            reason = "All assigned documents have a confirmed send."
        elif str(destination.passenger_id) in active:
            reason = "An earlier update is queued, in progress, or has an unknown outcome."
        elif (
            destination.reason
            or not destination.phone_number
            or not destination.recipient_id
            or not destination.broadcast_group_id
        ):
            reason = destination.reason or "Link an opted-in WhatsApp contact for this traveller."
        rows.append(
            DocumentUpdateRecipient(
                passenger_id=destination.passenger_id,
                passenger_name=display_names.get(
                    destination.passenger_id, destination.passenger_name
                ),
                phone_number=destination.phone_number,
                recipient_id=destination.recipient_id,
                broadcast_group_id=destination.broadcast_group_id,
                document_count=len(ids),
                confirmed_count=len(ids & confirmed),
                eligible=reason is None,
                reason=reason,
                latest_update_status=latest.get(str(destination.passenger_id)),
                latest_update_error=latest_errors.get(str(destination.passenger_id)),
                latest_update_at=latest_times.get(str(destination.passenger_id)),
            )
        )
    template = await configured_template_name(session, "document_update")
    language = template_language("document_update")
    settings = get_settings()
    configured = bool(
        template and settings.whatsapp_access_token and settings.whatsapp_phone_number_id
    )
    token = fingerprint(
        {
            "agency": group.agency_id,
            "group": group.id,
            "type": document_type,
            "broadcast": broadcast_group_id,
            "template": template,
            "language": language,
            "rows": [row.model_dump(mode="json") for row in rows],
            "documents": sorted(
                (str(doc.id), str(doc.passenger_id), str(doc.updated_at)) for doc in documents
            ),
            "updates": sorted(
                (passenger, latest_receipts[passenger], state)
                for passenger, state in latest.items()
            ),
            "active_updates": sorted(active),
        }
    )
    return DocumentUpdatePreview(
        group_id=group.id,
        document_type=document_type,
        preview_token=token,
        template_name=template,
        template_language=language,
        can_send=configured,
        configuration_error=None
        if configured
        else "Configure the document update template and WhatsApp credentials first.",
        recipients=rows,
    )
