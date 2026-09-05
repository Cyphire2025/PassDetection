"""Durable cross-route progress for every WhatsApp broadcast engine."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.domain.value_objects.travel_document_taxonomy import document_type_label
from app.infrastructure.database.models import (
    ClientGroupModel,
    DocumentWhatsAppDeliveryModel,
    PassengerQrWhatsAppDeliveryModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.whatsapp_activity_schemas import (
    WhatsAppActivityFailureResponse,
    WhatsAppActivityKind,
    WhatsAppActivitySummaryResponse,
)
from app.presentation.dependencies.auth import WHATSAPP_BROADCAST_ROLES, require_role

router = APIRouter()

ACTIVITY_ROLES = [
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
]
ACTIVE_STATUSES = frozenset({"queued", "processing"})
SUCCESS_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})
UNCERTAIN_STATUSES = frozenset({"delivery_unknown", "stalled"})
KNOWN_STATUSES = ACTIVE_STATUSES | SUCCESS_STATUSES | UNCERTAIN_STATUSES
ACTIVITY_STALE_AFTER = timedelta(minutes=30)

_BROADCAST_TITLES = {
    "welcome": "Welcome message broadcast",
    "passport_link": "Passport link broadcast",
    "reminder": "Reminder broadcast",
}


def _status_aggregates(
    status_column: Any,
    status_updated_column: Any,
    *,
    stale_cutoff: datetime,
) -> tuple[Any, ...]:
    is_active = status_column.in_(ACTIVE_STATUSES)
    is_stale = and_(is_active, status_updated_column < stale_cutoff)
    is_queued = and_(is_active, ~is_stale)
    is_unknown = or_(status_column.in_(UNCERTAIN_STATUSES), is_stale)
    is_failed = ~status_column.in_(KNOWN_STATUSES)
    return (
        func.count().label("total"),
        func.count().filter(is_queued).label("queued"),
        func.count().filter(status_column.in_(SUCCESS_STATUSES)).label("sent"),
        func.count().filter(is_failed).label("failed"),
        func.count().filter(is_unknown).label("delivery_unknown"),
    )


def _scope_client_group_statement(statement: Any, current_user: User) -> Any:
    return AuthorizationPolicy.apply_group_visibility_scope(statement, current_user)


def _broadcast_activity_statement(
    *,
    batch_id: uuid.UUID,
    current_user: User,
    stale_cutoff: datetime,
) -> Any:
    statement = (
        select(
            WhatsAppMessageLogModel.batch_id.label("activity_id"),
            WhatsAppBroadcastGroupModel.id.label("source_group_id"),
            WhatsAppBroadcastGroupModel.name.label("context_label"),
            WhatsAppMessageLogModel.message_type.label("activity_label"),
            *_status_aggregates(
                WhatsAppMessageLogModel.status,
                WhatsAppMessageLogModel.status_updated_at,
                stale_cutoff=stale_cutoff,
            ),
            func.min(WhatsAppMessageLogModel.created_at).label("started_at"),
            func.max(WhatsAppMessageLogModel.status_updated_at).label("updated_at"),
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id == WhatsAppMessageLogModel.broadcast_group_id,
        )
        .where(WhatsAppMessageLogModel.batch_id == batch_id)
        .group_by(
            WhatsAppMessageLogModel.batch_id,
            WhatsAppBroadcastGroupModel.id,
            WhatsAppBroadcastGroupModel.name,
            WhatsAppMessageLogModel.message_type,
        )
    )
    if current_user.role != UserRole.SUPER_ADMIN:
        statement = statement.where(WhatsAppBroadcastGroupModel.agency_id == current_user.agency_id)
    return statement


def _document_activity_statement(
    *,
    batch_id: uuid.UUID,
    current_user: User,
    stale_cutoff: datetime,
) -> Any:
    statement = (
        select(
            DocumentWhatsAppDeliveryModel.send_batch_id.label("activity_id"),
            ClientGroupModel.id.label("source_group_id"),
            ClientGroupModel.name.label("context_label"),
            DocumentWhatsAppDeliveryModel.document_type.label("activity_label"),
            *_status_aggregates(
                DocumentWhatsAppDeliveryModel.status,
                DocumentWhatsAppDeliveryModel.status_updated_at,
                stale_cutoff=stale_cutoff,
            ),
            func.min(DocumentWhatsAppDeliveryModel.created_at).label("started_at"),
            func.max(DocumentWhatsAppDeliveryModel.status_updated_at).label("updated_at"),
        )
        .join(
            ClientGroupModel,
            ClientGroupModel.id == DocumentWhatsAppDeliveryModel.group_id,
        )
        .where(DocumentWhatsAppDeliveryModel.send_batch_id == batch_id)
        .group_by(
            DocumentWhatsAppDeliveryModel.send_batch_id,
            ClientGroupModel.id,
            ClientGroupModel.name,
            DocumentWhatsAppDeliveryModel.document_type,
        )
    )
    return _scope_client_group_statement(statement, current_user)


def _qr_activity_statement(
    *,
    batch_id: uuid.UUID,
    current_user: User,
    stale_cutoff: datetime,
) -> Any:
    statement = (
        select(
            PassengerQrWhatsAppDeliveryModel.send_batch_id.label("activity_id"),
            ClientGroupModel.id.label("source_group_id"),
            ClientGroupModel.name.label("context_label"),
            *_status_aggregates(
                PassengerQrWhatsAppDeliveryModel.status,
                PassengerQrWhatsAppDeliveryModel.status_updated_at,
                stale_cutoff=stale_cutoff,
            ),
            func.min(PassengerQrWhatsAppDeliveryModel.created_at).label("started_at"),
            func.max(PassengerQrWhatsAppDeliveryModel.status_updated_at).label("updated_at"),
        )
        .join(
            ClientGroupModel,
            ClientGroupModel.id == PassengerQrWhatsAppDeliveryModel.group_id,
        )
        .where(PassengerQrWhatsAppDeliveryModel.send_batch_id == batch_id)
        .group_by(
            PassengerQrWhatsAppDeliveryModel.send_batch_id,
            ClientGroupModel.id,
            ClientGroupModel.name,
        )
    )
    return _scope_client_group_statement(statement, current_user)


def _activity_statement(
    *,
    kind: WhatsAppActivityKind,
    batch_id: uuid.UUID,
    current_user: User,
    stale_cutoff: datetime,
) -> Any:
    if kind == "broadcast":
        return _broadcast_activity_statement(
            batch_id=batch_id,
            current_user=current_user,
            stale_cutoff=stale_cutoff,
        )
    if kind == "document":
        return _document_activity_statement(
            batch_id=batch_id,
            current_user=current_user,
            stale_cutoff=stale_cutoff,
        )
    return _qr_activity_statement(
        batch_id=batch_id,
        current_user=current_user,
        stale_cutoff=stale_cutoff,
    )


def _failed_status_predicate(status_column: Any) -> Any:
    return ~status_column.in_(KNOWN_STATUSES)


def _broadcast_failures_statement(*, batch_id: uuid.UUID, current_user: User) -> Any:
    statement = (
        select(
            WhatsAppBroadcastRecipientModel.name.label("recipient_name"),
            WhatsAppBroadcastRecipientModel.normalized_phone_number.label("phone_number"),
            WhatsAppMessageLogModel.error_message.label("error_message"),
        )
        .join(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.id == WhatsAppMessageLogModel.recipient_id,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id == WhatsAppMessageLogModel.broadcast_group_id,
        )
        .where(
            WhatsAppMessageLogModel.batch_id == batch_id,
            _failed_status_predicate(WhatsAppMessageLogModel.status),
        )
        .order_by(
            WhatsAppBroadcastRecipientModel.name.asc().nulls_last(),
            WhatsAppBroadcastRecipientModel.normalized_phone_number.asc(),
        )
    )
    if current_user.role != UserRole.SUPER_ADMIN:
        statement = statement.where(WhatsAppBroadcastGroupModel.agency_id == current_user.agency_id)
    return statement


def _document_failures_statement(*, batch_id: uuid.UUID, current_user: User) -> Any:
    statement = (
        select(
            DocumentWhatsAppDeliveryModel.passenger_name.label("recipient_name"),
            DocumentWhatsAppDeliveryModel.normalized_phone_number.label("phone_number"),
            DocumentWhatsAppDeliveryModel.error_message.label("error_message"),
        )
        .join(
            ClientGroupModel,
            ClientGroupModel.id == DocumentWhatsAppDeliveryModel.group_id,
        )
        .where(
            DocumentWhatsAppDeliveryModel.send_batch_id == batch_id,
            _failed_status_predicate(DocumentWhatsAppDeliveryModel.status),
        )
        .order_by(
            DocumentWhatsAppDeliveryModel.passenger_name.asc(),
            DocumentWhatsAppDeliveryModel.normalized_phone_number.asc(),
        )
    )
    return _scope_client_group_statement(statement, current_user)


def _qr_failures_statement(*, batch_id: uuid.UUID, current_user: User) -> Any:
    statement = (
        select(
            PassengerQrWhatsAppDeliveryModel.passenger_name.label("recipient_name"),
            PassengerQrWhatsAppDeliveryModel.normalized_phone_number.label("phone_number"),
            PassengerQrWhatsAppDeliveryModel.error_message.label("error_message"),
        )
        .join(
            ClientGroupModel,
            ClientGroupModel.id == PassengerQrWhatsAppDeliveryModel.group_id,
        )
        .where(
            PassengerQrWhatsAppDeliveryModel.send_batch_id == batch_id,
            _failed_status_predicate(PassengerQrWhatsAppDeliveryModel.status),
        )
        .order_by(
            PassengerQrWhatsAppDeliveryModel.passenger_name.asc(),
            PassengerQrWhatsAppDeliveryModel.normalized_phone_number.asc(),
        )
    )
    return _scope_client_group_statement(statement, current_user)


def _failures_statement(
    *,
    kind: WhatsAppActivityKind,
    batch_id: uuid.UUID,
    current_user: User,
) -> Any:
    if kind == "broadcast":
        return _broadcast_failures_statement(batch_id=batch_id, current_user=current_user)
    if kind == "document":
        return _document_failures_statement(batch_id=batch_id, current_user=current_user)
    return _qr_failures_statement(batch_id=batch_id, current_user=current_user)


def _ensure_kind_access(kind: WhatsAppActivityKind, current_user: User) -> None:
    if kind == "broadcast" and current_user.role not in WHATSAPP_BROADCAST_ROLES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast activity not found",
        )


def _activity_title(kind: WhatsAppActivityKind, activity_label: str | None) -> str:
    if kind == "broadcast":
        return _BROADCAST_TITLES.get(activity_label or "", "WhatsApp message broadcast")
    if kind == "document":
        return f"{document_type_label(activity_label or '')} broadcast"
    return "QR code broadcast"


@router.get(
    "/activities/{kind}/{batch_id}",
    response_model=WhatsAppActivitySummaryResponse,
)
async def get_whatsapp_activity_summary(
    kind: Literal["broadcast", "document", "qr"],
    batch_id: uuid.UUID,
    current_user: User = Depends(require_role(ACTIVITY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppActivitySummaryResponse:
    """Return small, resumable progress data for one send batch."""

    _ensure_kind_access(kind, current_user)
    result = await session.execute(
        _activity_statement(
            kind=kind,
            batch_id=batch_id,
            current_user=current_user,
            stale_cutoff=datetime.now(tz=UTC) - ACTIVITY_STALE_AFTER,
        )
    )
    summary = result.one_or_none()
    if summary is None or int(summary.total) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast activity not found",
        )

    activity_label = getattr(summary, "activity_label", None)
    return WhatsAppActivitySummaryResponse(
        activity_id=summary.activity_id,
        kind=kind,
        title=_activity_title(kind, activity_label),
        context_label=summary.context_label,
        source_group_id=summary.source_group_id,
        document_type=activity_label if kind == "document" else None,
        total=int(summary.total),
        queued=int(summary.queued),
        sent=int(summary.sent),
        failed=int(summary.failed),
        delivery_unknown=int(summary.delivery_unknown),
        started_at=summary.started_at,
        updated_at=summary.updated_at,
    )


@router.get(
    "/activities/{kind}/{batch_id}/failures",
    response_model=list[WhatsAppActivityFailureResponse],
)
async def get_whatsapp_activity_failures(
    kind: Literal["broadcast", "document", "qr"],
    batch_id: uuid.UUID,
    current_user: User = Depends(require_role(ACTIVITY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[WhatsAppActivityFailureResponse]:
    """Reveal failed recipient names only when the operator expands them."""

    _ensure_kind_access(kind, current_user)
    result = await session.execute(
        _failures_statement(
            kind=kind,
            batch_id=batch_id,
            current_user=current_user,
        )
    )
    return [
        WhatsAppActivityFailureResponse(
            recipient_name=row.recipient_name or row.phone_number,
            phone_number=row.phone_number,
            error_message=row.error_message,
        )
        for row in result.all()
    ]
