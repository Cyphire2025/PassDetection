"""Seek actual source people before delivery-phone consolidation.

Each UNION branch is capped before the outer sort: at most 303 rows can reach
that sort, independent of retained history size. A cursor names source kind and
UUID. Legacy cursors are accepted as passport-submission positions.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, String, cast, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
)
from app.infrastructure.database.traveller_reuse_models import TravellerReconciliationJobModel
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


@dataclass(frozen=True, slots=True)
class ReconciliationSource:
    id: uuid.UUID
    source_kind: str
    extraction_revision: int
    status: str
    confirmed_fields: Mapping[str, object] | None
    staff_metadata: Mapping[str, object] | None
    display_name: str | None = None
    phone: str | None = None


def source_cursor(kind: str, identifier: uuid.UUID) -> str:
    return f"v2:{kind}:{identifier}"


def source_fingerprint(crypto: TravellerReuseCrypto, agency_id: uuid.UUID, company_id: uuid.UUID,
    source: ReconciliationSource,
) -> str:
    payload = {"status": source.status, "revision": source.extraction_revision,
        "confirmed_fields": source.confirmed_fields or {}, "staff_metadata": source.staff_metadata or {},
        "display_name": source.display_name, "phone": source.phone}
    return crypto.scoped_digest("reconciliation-source", agency_id, company_id, source.source_kind,
        str(source.id), json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _source_query(kind: str, agency_id: uuid.UUID, group_id: uuid.UUID) -> Select[Any]:
    passport = PassportSubmissionModel
    if kind == "passport_submission":
        return select(passport.id, literal(kind).label("source_kind"), passport.extraction_revision,
            cast(passport.status, String).label("status"), passport.confirmed_fields, passport.staff_metadata,
            passport.created_at.label("source_created_at"), passport.created_at.label("link_created_at"),
            passport.client_name.label("display_name"), passport.client_phone.label("phone")).where(
            passport.agency_id == agency_id, passport.group_id == group_id)
    return roster_source_query(kind, agency_id).where(
        ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id)


def roster_source_query(kind: str, agency_id: uuid.UUID) -> Select[Any]:
    """Shared durable roster population for reconciliation and company totals."""
    passport = PassportSubmissionModel
    models: dict[str, type[WhatsAppBroadcastRecipientModel] | type[WhatsAppBroadcastRejectedContactModel]] = {
        "whatsapp_recipient": WhatsAppBroadcastRecipientModel,
        "whatsapp_rejected": WhatsAppBroadcastRejectedContactModel}
    if kind not in models:
        raise ValueError("Unsupported reconciliation source")
    model = models[kind]
    name = WhatsAppBroadcastRecipientModel.name if kind == "whatsapp_recipient" else WhatsAppBroadcastRejectedContactModel.raw_name
    phone = WhatsAppBroadcastRecipientModel.phone_number if kind == "whatsapp_recipient" else WhatsAppBroadcastRejectedContactModel.raw_phone_number
    query = select(model.id, literal(kind).label("source_kind"), literal(0).label("extraction_revision"),
        literal("imported_roster").label("status"), literal(None, type_=passport.confirmed_fields.type).label("confirmed_fields"),
        model.imported_fields.label("staff_metadata"), model.created_at.label("source_created_at"),
        ClientGroupWhatsAppBroadcastLinkModel.created_at.label("link_created_at"),
        name.label("display_name"), phone.label("phone")).join(ClientGroupWhatsAppBroadcastLinkModel,
        (ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == model.broadcast_group_id)
        & (ClientGroupWhatsAppBroadcastLinkModel.agency_id == model.agency_id)).join(WhatsAppBroadcastGroupModel,
        (WhatsAppBroadcastGroupModel.id == model.broadcast_group_id)
        & (WhatsAppBroadcastGroupModel.agency_id == model.agency_id)).where(
        model.agency_id == agency_id)
    if model is WhatsAppBroadcastRecipientModel:
        recipient = WhatsAppBroadcastRecipientModel
        query = query.where(recipient.removed_at.is_(None), recipient.merged_into_recipient_id.is_(None),
            recipient.suppressed_by_roster_resolution_id.is_(None), recipient.is_source_managed.is_(False))
    return query


async def current_source(session: AsyncSession, *, agency_id: uuid.UUID, group_id: uuid.UUID,
    kind: str, identifier: uuid.UUID,
) -> ReconciliationSource | None:
    query = _source_query(kind, agency_id, group_id)
    row = (await session.execute(query.where(query.selected_columns.id == identifier).limit(1)
        .with_for_update(read=True, of=query.selected_columns.id))).one_or_none()
    return ReconciliationSource(row.id, row.source_kind, row.extraction_revision,
        row.status, row.confirmed_fields, row.staff_metadata, row.display_name, row.phone) if row is not None else None


async def source_page(session: AsyncSession, job: TravellerReconciliationJobModel, size: int) -> list[ReconciliationSource]:
    kind, after = "passport_submission", None
    if job.cursor:
        if job.cursor.startswith("v2:"):
            _, kind, value = job.cursor.split(":", 2)
            after = uuid.UUID(value)
        else:
            after = uuid.UUID(job.cursor)
    branches = []
    for source_kind in ("passport_submission", "whatsapp_recipient", "whatsapp_rejected"):
        if kind > source_kind:
            continue
        source = _source_query(source_kind, job.agency_id, job.group_id).subquery()
        query = select(source).where(source.c.source_created_at <= job.created_at, source.c.link_created_at <= job.created_at)
        if after is not None and kind == source_kind:
            query = query.where(source.c.id > after)
        branches.append(select(query.order_by(source.c.id).limit(size + 1).subquery()))
    if not branches:
        raise ValueError("Unsupported reconciliation cursor")
    combined = union_all(*branches).subquery()
    rows = (await session.execute(select(combined).order_by(combined.c.source_kind, combined.c.id).limit(size + 1))).all()
    return [ReconciliationSource(row.id, row.source_kind, row.extraction_revision,
        row.status, row.confirmed_fields, row.staff_metadata, row.display_name, row.phone) for row in rows]
