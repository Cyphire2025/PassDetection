"""Export access, roster identity and scalar value policies."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppMessageLogModel,
)
from app.presentation.api.v1.routes.passport_export_support import (
    _WHATSAPP_EMAIL_IMPORTED_KEYS,
    _imported_zone_name,
    _normalized_imported_field_key,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppRecipientResponse,
    WhatsAppRecipientRosterItemResponse,
)

_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_MESSAGE_LABELS = {
    "welcome": "Welcome",
    "passport_link": "Passport link",
    "reminder": "Reminder",
    "group_invite": "Group invite",
}

_SourceKey = tuple[uuid.UUID, uuid.UUID]

_SOURCE_QUERY_BATCH = 1_000


def _stale_rows() -> HTTPException:
    return HTTPException(
        409,
        "One or more export rows changed or are not accessible. Refresh the roster and export again.",
    )


def _roster_identity(row: WhatsAppRecipientRosterItemResponse) -> tuple[str, uuid.UUID]:
    if row.recipient is not None:
        return "recipient", row.recipient.id
    if row.rejected_contact is not None:
        return "rejected", row.rejected_contact.id
    if row.replaced_recipient is not None:
        return "replaced", row.replaced_recipient.recipient_id
    assert row.unidentified_upload is not None
    return "unidentified", row.unidentified_upload.submission_id


async def _exportable_links(
    session: AsyncSession,
    broadcast: WhatsAppBroadcastGroupModel,
    user: User,
) -> list[tuple[ClientGroupModel, ClientGroupWhatsAppBroadcastLinkModel]]:
    statement = (
        select(ClientGroupModel, ClientGroupWhatsAppBroadcastLinkModel)
        .join(
            ClientGroupWhatsAppBroadcastLinkModel,
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == ClientGroupModel.id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == broadcast.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == broadcast.agency_id,
            ClientGroupModel.agency_id == broadcast.agency_id,
            ClientGroupModel.deleted_at.is_(None),
        )
        .order_by(ClientGroupModel.name, ClientGroupModel.id)
    )
    rows = (
        await session.execute(AuthorizationPolicy.apply_group_visibility_scope(statement, user))
    ).all()
    policy = AuthorizationPolicy(session)
    result = []
    for group, link in rows:
        try:
            await policy.require_export_data(user, group)
        except AuthorizationError:
            continue
        result.append((group, link))
    return result


async def _latest_attempt_values(
    session: AsyncSession,
    broadcast: WhatsAppBroadcastGroupModel,
    recipient_ids: set[uuid.UUID],
) -> dict[uuid.UUID, dict[str, Any]]:
    if not recipient_ids:
        return {}
    # Select scalars only: media IDs, bodies and tokens never enter this export.
    ranked = (
        select(
            WhatsAppMessageLogModel.recipient_id,
            WhatsAppMessageLogModel.message_type,
            WhatsAppMessageLogModel.status,
            WhatsAppMessageLogModel.error_message,
            WhatsAppMessageLogModel.created_at,
            WhatsAppMessageLogModel.template_name,
            WhatsAppMessageLogModel.normalized_phone_number,
            func.row_number()
            .over(
                partition_by=(
                    WhatsAppMessageLogModel.recipient_id,
                    WhatsAppMessageLogModel.message_type,
                ),
                order_by=(
                    WhatsAppMessageLogModel.created_at.desc(),
                    WhatsAppMessageLogModel.id.desc(),
                ),
            )
            .label("position"),
        )
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == broadcast.id,
            WhatsAppMessageLogModel.agency_id == broadcast.agency_id,
            WhatsAppMessageLogModel.recipient_id.in_(recipient_ids),
        )
        .subquery()
    )
    result: dict[uuid.UUID, dict[str, Any]] = defaultdict(dict)
    for row in (await session.execute(select(ranked).where(ranked.c.position == 1))).all():
        label = _MESSAGE_LABELS.get(row.message_type, row.message_type)
        result[row.recipient_id].update(
            {
                f"{label} latest attempt status": row.status,
                f"{label} latest attempt error": row.error_message,
                f"{label} latest attempt at": row.created_at,
                f"{label} latest attempt template": row.template_name,
                f"{label} latest attempt phone": row.normalized_phone_number,
            }
        )
    return dict(result)


def _delivery_values(recipient: WhatsAppRecipientResponse | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    statuses = (
        {state.message_type: state for state in recipient.message_statuses} if recipient else {}
    )
    for message_type, label in _MESSAGE_LABELS.items():
        state = statuses.get(message_type)
        values[f"{label} status"] = state.status if state else "not_sent"
        values[f"{label} latest resend status"] = state.latest_resend_status if state else None
        values[f"{label} already sent"] = state.already_sent if state else False
        values[f"{label} resend blocked"] = state.resend_blocked if state else False
        values[f"{label} status updated at"] = state.status_updated_at if state else None
    return values


def _broadcast_import_contact_values(fields: dict[str, Any]) -> dict[str, Any]:
    """Unambiguous contact context for this exact broadcast row, never a phone match."""
    emails: dict[str, str] = {}
    for key, value in fields.items():
        if _normalized_imported_field_key(str(key)) not in _WHATSAPP_EMAIL_IMPORTED_KEYS:
            continue
        email = " ".join(str(value or "").strip().split())
        if email and email.casefold() not in {"null", "none", "n/a", "na"}:
            emails.setdefault(email.casefold(), email)
    return {
        "WhatsApp Email": next(iter(emails.values())) if len(emails) == 1 else None,
        "Zone Name": _imported_zone_name(fields),
    }


# Preserve the existing public import and pickle identities.
_stale_rows.__module__ = "app.presentation.api.v1.routes.whatsapp_exports"
_roster_identity.__module__ = "app.presentation.api.v1.routes.whatsapp_exports"
_exportable_links.__module__ = "app.presentation.api.v1.routes.whatsapp_exports"
_latest_attempt_values.__module__ = "app.presentation.api.v1.routes.whatsapp_exports"
_delivery_values.__module__ = "app.presentation.api.v1.routes.whatsapp_exports"
_broadcast_import_contact_values.__module__ = "app.presentation.api.v1.routes.whatsapp_exports"
