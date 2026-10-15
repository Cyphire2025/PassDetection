"""Complete retained delivery history; observations never recover or retry work."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.read_context import MCPReadContext
from app.application.mcp.read_projection import scrub_read
from app.domain.whatsapp_delivery_status import WHATSAPP_STALE_CLAIM_AGE
from app.infrastructure.database.models import (
    ClientGroupModel,
    DocumentWhatsAppDeliveryModel,
    PassengerQrWhatsAppDeliveryModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeAttemptModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.mcp_read_page import read_page

# Server-owned projections. Never accept arbitrary tables or caller-selected SQL.
# Each reviewed table has a different set of optional projection columns.
DELIVERY_MODELS: dict[str, tuple[Any, str, str | None]] = {
    "document": (DocumentWhatsAppDeliveryModel, "send_batch_id", "passenger_id"),
    "qr": (PassengerQrWhatsAppDeliveryModel, "send_batch_id", "passenger_id"),
    "broadcast": (WhatsAppMessageLogModel, "batch_id", None),
    "welcome": (WhatsAppPhoneWelcomeAttemptModel, "batch_id", None),
}
DELIVERY_FIELDS = {
    "document": "document_batch_id distributed_document_id document_type document_filename passenger_id passenger_name attempt_count created_by_user_id updated_at",
    "qr": "passenger_id passenger_name attempt_count created_by_user_id updated_at",
    "broadcast": "recipient_id message_type template_language is_explicit_resend",
    "welcome": "recipient_name passenger_ids created_by_user_id updated_at",
}


class MCPDeliveryReadService(MCPReadContext):
    def __init__(self, session: AsyncSession, *, cursor_secret: str):
        super().__init__(session, cursor_secret=cursor_secret, namespace="mcp-delivery-read-v1")

    async def list_records(self, *, user_id: UUID, kind: str, agency_id: UUID | None = None,
        group_id: UUID | None = None, broadcast_id: UUID | None = None, batch_id: UUID | None = None,
        passenger_id: UUID | None = None, recipient_id: UUID | None = None, status: str | None = None,
        message_type: str | None = None, include_contact_details: bool = False,
        include_deleted: bool = False, include_archived: bool = False,
        page_size: int = 50, cursor: str | None = None) -> dict[str, Any]:
        if kind not in DELIVERY_MODELS:
            raise ValueError("Choose document, qr, broadcast or welcome delivery records")
        if status is not None and not 1 <= len(status) <= 50:
            raise ValueError("Delivery status must contain 1 to 50 characters")
        actor = await self._actor(user_id, page_size)
        await self._agency(agency_id)
        model, batch_column, passenger_column = DELIVERY_MODELS[kind]
        if group_id is not None:
            group = await self._group(actor, group_id, agency_id, include_deleted)
            agency_id = group.agency_id
        if broadcast_id is not None:
            statement = select(WhatsAppBroadcastGroupModel.agency_id).where(WhatsAppBroadcastGroupModel.id == broadcast_id)
            broadcast_agency = await self.session.scalar(statement)
            if broadcast_agency is None or agency_id is not None and agency_id != broadcast_agency:
                raise ValueError("Broadcast was not found in the requested agency")
            agency_id = broadcast_agency
        binding = dict(query="delivery", actor=user_id, kind=kind, agency_id=agency_id, group_id=group_id,
            broadcast_id=broadcast_id, batch_id=batch_id, passenger_id=passenger_id, recipient_id=recipient_id,
            status=status, message_type=message_type, include_contact_details=include_contact_details,
            include_deleted=include_deleted, include_archived=include_archived, page_size=page_size)
        state, page = self._state(cursor, **binding)
        columns = [model.id, model.agency_id, model.broadcast_group_id, getattr(model, batch_column).label("batch_id"),
            model.status, model.status_updated_at, model.provider_status_at, model.provider_message_id,
            model.template_name, model.created_at, func.substr(model.error_message, 1, 2000).label("error_message"),
            (func.length(model.error_message) > 2000).label("error_message_truncated")]
        columns.extend(getattr(model, name) for name in DELIVERY_FIELDS[kind].split())
        if kind != "broadcast":
            columns.append(model.group_id)
        if include_contact_details:
            columns.append(model.normalized_phone_number)
            if kind in {"document", "qr"}:
                columns.extend((model.phone_number, model.passport_number))
        statement = select(*columns)
        if agency_id is not None:
            statement = statement.where(model.agency_id == agency_id)
        if kind != "broadcast":
            join = statement.outerjoin if kind == "welcome" else statement.join
            statement = join(ClientGroupModel, (ClientGroupModel.id == model.group_id)
                & (ClientGroupModel.agency_id == model.agency_id))
            if not include_deleted:
                statement = statement.where(or_(model.group_id.is_(None),
                    ClientGroupModel.deleted_at.is_(None) & (ClientGroupModel.status != "deleted")))
            elif kind == "welcome":
                statement = statement.where(or_(model.group_id.is_(None), ClientGroupModel.id.is_not(None)))
        # Null broadcast IDs are legitimate private document/QR/welcome attempts;
        # a non-null inconsistent tenant link must never masquerade as one.
        statement = statement.outerjoin(WhatsAppBroadcastGroupModel,
            (WhatsAppBroadcastGroupModel.id == model.broadcast_group_id)
            & (WhatsAppBroadcastGroupModel.agency_id == model.agency_id)).where(
                or_(model.broadcast_group_id.is_(None), WhatsAppBroadcastGroupModel.id.is_not(None)))
        if not include_archived:
            statement = statement.where(WhatsAppBroadcastGroupModel.archived_at.is_(None))
        for identifier, column, label in (
            (group_id, "group_id" if kind != "broadcast" else None, "Group"),
            (broadcast_id, "broadcast_group_id", "Broadcast"),
            (batch_id, batch_column, "Batch"), (passenger_id, passenger_column, "Passenger"),
            (recipient_id, "recipient_id" if hasattr(model, "recipient_id") else None, "Recipient"),
        ):
            if identifier is not None:
                if column is None:
                    raise ValueError(f"{label} filtering is unavailable for this delivery kind")
                statement = statement.where(getattr(model, column) == identifier)
        if status is not None:
            statement = statement.where(model.status == status)
        if message_type is not None:
            if kind != "broadcast":
                raise ValueError("Message-type filtering applies to broadcast attempts")
            statement = statement.where(model.message_type == message_type)
        count_statement = statement.with_only_columns(model.status, func.count(model.id), maintain_column_froms=True)
        counts = (await self.session.execute(count_statement.where(model.created_at <= page["cutoff"]).group_by(model.status))).all()
        rows = await read_page(self.session, statement, model, **page)
        now = datetime.now(UTC)
        for row in rows:
            stamp = row["status_updated_at"]
            stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp
            row["effective_status"] = "stalled" if row["status"] in {"queued", "processing"} and stamp < now - WHATSAPP_STALE_CLAIM_AGE else row["status"]
            row["detail_reference"] = {"view": "delivery_record", "parameters": {"kind": kind, "record_id": str(row["id"]), "agency_id": str(row["agency_id"])}}
        result = self._result(rows, state, page_size,
            "Retained delivery attempts, not unique people. Provider acceptance/submitted and sent are separate from confirmed delivered/read. Stalled is an observational overlay; stored rows are unchanged. Detail references expose full saved message/template/error fields without file capabilities. No refresh, recovery, retry or send.")
        result["items"], withheld = scrub_read(result["items"])
        result.update(delivery_kind=kind, status_counts={state_name: int(count) for state_name, count in counts},
            total_matching_attempts=sum(int(count) for _, count in counts), withheld_fields_count=len(withheld))
        if include_contact_details:
            await AuditLogRepository(self.session).record(action="mcp.delivery.contact_read", entity_type="delivery",
                user_id=actor.id, agency_id=agency_id, metadata={"kind": kind, "authorized_result_count": len(result["items"])})
        return result
