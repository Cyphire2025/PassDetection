"""Stable accepted/rejected roster ordering and the scoped next-order query."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
)
from app.presentation.api.v1.routes.whatsapp_contact_rejections import _rejected_contact_fingerprint
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppRecipientInput,
    WhatsAppRejectedContactInput,
)


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _roster_source_sort_key(
    imported_fields: dict[str, str],
    *,
    fallback_source_file: str = "",
    fallback_source_sheet: str = "",
    fallback_source_row: int | None = None,
    stable_index: int,
) -> tuple[int, str, int, str, int, int]:
    source_file = (imported_fields.get("source_file") or fallback_source_file or "").casefold()
    source_sheet = (imported_fields.get("source_sheet") or fallback_source_sheet or "").casefold()
    source_row = _positive_int(imported_fields.get("source_row")) or fallback_source_row or 0
    source_order = _positive_int(imported_fields.get("source_order"))
    is_imported = bool(source_file or source_sheet or source_row or source_order)
    return (
        0 if is_imported else 1,
        source_file,
        source_order or source_row,
        source_sheet,
        source_row,
        stable_index,
    )


def _new_roster_display_orders(
    *,
    normalized_contacts: dict[str, WhatsAppRecipientInput],
    rejected_contacts: list[WhatsAppRejectedContactInput],
    existing_by_phone: dict[str, WhatsAppBroadcastRecipientModel],
    existing_by_fingerprint: dict[str, WhatsAppBroadcastRejectedContactModel],
    start_order: int,
) -> tuple[dict[str, int], dict[str, int]]:
    candidates: list[
        tuple[
            tuple[int, str, int, str, int, int],
            Literal["recipient", "rejected"],
            str,
        ]
    ] = []
    stable_index = 0
    for normalized_phone, contact in normalized_contacts.items():
        if normalized_phone not in existing_by_phone:
            candidates.append(
                (
                    _roster_source_sort_key(
                        contact.imported_fields,
                        stable_index=stable_index,
                    ),
                    "recipient",
                    normalized_phone,
                )
            )
        stable_index += 1
    for rejected_contact in rejected_contacts:
        fingerprint = _rejected_contact_fingerprint(rejected_contact)
        if fingerprint not in existing_by_fingerprint:
            candidates.append(
                (
                    _roster_source_sort_key(
                        rejected_contact.imported_fields,
                        fallback_source_file=rejected_contact.source_file_name,
                        fallback_source_sheet=rejected_contact.sheet_name,
                        fallback_source_row=rejected_contact.row_number,
                        stable_index=stable_index,
                    ),
                    "rejected",
                    fingerprint,
                )
            )
        stable_index += 1

    recipient_orders: dict[str, int] = {}
    rejected_orders: dict[str, int] = {}
    for offset, (_, kind, identity) in enumerate(sorted(candidates)):
        display_order = start_order + offset
        if kind == "recipient":
            recipient_orders[identity] = display_order
        else:
            rejected_orders[identity] = display_order
    return recipient_orders, rejected_orders


async def _next_roster_display_order(
    session: AsyncSession,
    group_id: uuid.UUID,
) -> int:
    existing_orders = union_all(
        select(WhatsAppBroadcastRecipientModel.display_order.label("display_order")).where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
        ),
        select(WhatsAppBroadcastRejectedContactModel.display_order.label("display_order")).where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group_id,
        ),
    ).subquery()
    result = await session.execute(
        select(func.coalesce(func.max(existing_orders.c.display_order), 0))
    )
    return int(result.scalar_one()) + 1
