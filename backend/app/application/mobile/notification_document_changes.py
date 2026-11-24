"""Privacy-safe document change notification production."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.notification_contracts import (
    _LOCK_SCREEN_TITLE,
    _RECIPIENT_PAGE_SIZE,
    DocumentChangeNotificationCounts,
)
from app.application.mobile.passenger_notification_authority import retain_recipient_ids
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCGroupAccessModel,
    MobileNotificationModel,
)
from app.infrastructure.database.models import CoordinatorGroupAssignmentModel, UserModel


async def enqueue_personal_document_change_notifications(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    passenger_identity_ids: Sequence[uuid.UUID],
    operation: Literal["upsert", "delete"],
    dedupe_token: str,
    now: datetime | None = None,
) -> DocumentChangeNotificationCounts:
    """Queue generic refresh triggers without leaking passenger/document details.

    Passengers are targeted only by their exact mobile identity. Client managers
    and coordinators receive summary-level refresh prompts only when the matching
    role is enabled and they hold an explicit assignment to this group.
    """

    current = now or datetime.now(tz=UTC)
    if not access.is_enabled or access.revoked_at is not None:
        return DocumentChangeNotificationCounts()
    available_at = max(value for value in (current, access.access_starts_at) if value is not None)
    expires_at = access.access_expires_at
    if expires_at is not None and expires_at <= available_at:
        return DocumentChangeNotificationCounts()

    identities = tuple(sorted(set(passenger_identity_ids), key=str))
    passengers = 0
    managers = 0
    coordinators = 0
    if access.passenger_access_enabled and identities:
        passengers = await _enqueue_document_change_ids(
            session,
            recipient_ids=identities,
            recipient_type="passenger",
            access=access,
            operation=operation,
            dedupe_token=dedupe_token,
            available_at=available_at,
            expires_at=expires_at,
        )
    if access.client_manager_access_enabled:
        managers = await _enqueue_document_change_user_pages(
            session,
            statement=(
                select(UserModel.id)
                .join(
                    ClientManagerProfileModel,
                    ClientManagerProfileModel.user_id == UserModel.id,
                )
                .join(
                    ClientManagerGroupAssignmentModel,
                    ClientManagerGroupAssignmentModel.profile_id == ClientManagerProfileModel.id,
                )
                .where(
                    UserModel.agency_id == access.agency_id,
                    UserModel.role == "client_manager",
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                    ClientManagerProfileModel.agency_id == access.agency_id,
                    ClientManagerProfileModel.status == "active",
                    ClientManagerProfileModel.deleted_at.is_(None),
                    ClientManagerGroupAssignmentModel.agency_id == access.agency_id,
                    ClientManagerGroupAssignmentModel.gc_group_access_id == access.id,
                    ClientManagerGroupAssignmentModel.group_id == access.group_id,
                    ClientManagerGroupAssignmentModel.is_active.is_(True),
                    ClientManagerGroupAssignmentModel.revoked_at.is_(None),
                )
            ),
            recipient_type="client_manager",
            access=access,
            operation=operation,
            dedupe_token=dedupe_token,
            available_at=available_at,
            expires_at=expires_at,
        )
    if access.coordinator_access_enabled:
        coordinators = await _enqueue_document_change_user_pages(
            session,
            statement=(
                select(UserModel.id)
                .join(
                    CoordinatorGroupAssignmentModel,
                    CoordinatorGroupAssignmentModel.coordinator_user_id == UserModel.id,
                )
                .where(
                    UserModel.agency_id == access.agency_id,
                    UserModel.role == "agency_coordinator",
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                    CoordinatorGroupAssignmentModel.agency_id == access.agency_id,
                    CoordinatorGroupAssignmentModel.group_id == access.group_id,
                    CoordinatorGroupAssignmentModel.active.is_(True),
                )
            ),
            recipient_type="coordinator",
            access=access,
            operation=operation,
            dedupe_token=dedupe_token,
            available_at=available_at,
            expires_at=expires_at,
        )
    return DocumentChangeNotificationCounts(
        passengers=passengers,
        client_managers=managers,
        coordinators=coordinators,
    )


async def _enqueue_document_change_user_pages(
    session: AsyncSession,
    *,
    statement: Select[tuple[uuid.UUID]],
    recipient_type: Literal["client_manager", "coordinator"],
    access: GCGroupAccessModel,
    operation: Literal["upsert", "delete"],
    dedupe_token: str,
    available_at: datetime,
    expires_at: datetime | None,
) -> int:
    cursor: uuid.UUID | None = None
    inserted = 0
    while True:
        page_statement = statement
        if cursor is not None:
            page_statement = page_statement.where(UserModel.id > cursor)
        ids = list(
            (
                await session.execute(
                    page_statement.order_by(UserModel.id.asc()).limit(_RECIPIENT_PAGE_SIZE)
                )
            ).scalars()
        )
        if not ids:
            break
        inserted += await _enqueue_document_change_ids(
            session,
            recipient_ids=ids,
            recipient_type=recipient_type,
            access=access,
            operation=operation,
            dedupe_token=dedupe_token,
            available_at=available_at,
            expires_at=expires_at,
        )
        cursor = ids[-1]
        if len(ids) < _RECIPIENT_PAGE_SIZE:
            break
    return inserted


async def _enqueue_document_change_ids(
    session: AsyncSession,
    *,
    recipient_ids: Sequence[uuid.UUID],
    recipient_type: Literal["passenger", "client_manager", "coordinator"],
    access: GCGroupAccessModel,
    operation: Literal["upsert", "delete"],
    dedupe_token: str,
    available_at: datetime,
    expires_at: datetime | None,
) -> int:
    recipient_ids = await retain_recipient_ids(
        session, recipient_ids=recipient_ids, recipient_type=recipient_type, access=access
    )
    for recipient_id in recipient_ids:
        session.add(
            _personal_document_change_notification(
                recipient_id=recipient_id,
                recipient_type=recipient_type,
                access=access,
                operation=operation,
                dedupe_token=dedupe_token,
                available_at=available_at,
                expires_at=expires_at,
            )
        )
    if recipient_ids:
        await session.flush()
    return len(recipient_ids)


def _personal_document_change_notification(
    *,
    recipient_id: uuid.UUID,
    recipient_type: Literal["passenger", "client_manager", "coordinator"],
    access: GCGroupAccessModel,
    operation: Literal["upsert", "delete"],
    dedupe_token: str,
    available_at: datetime,
    expires_at: datetime | None,
) -> MobileNotificationModel:
    route_by_role = {
        "passenger": "documents",
        "client_manager": "readiness",
        "coordinator": "passengers",
    }
    title_by_role = {
        "passenger": "Travel documents updated",
        "client_manager": "Group readiness updated",
        "coordinator": "Passenger information updated",
    }
    body_by_role = {
        "passenger": "Open Global Connect Travels to refresh your travel documents.",
        "client_manager": "Open Global Connect Travels to refresh the group readiness summary.",
        "coordinator": "Open Global Connect Travels to refresh passenger information.",
    }
    route = route_by_role[recipient_type]
    is_passenger = recipient_type == "passenger"
    return MobileNotificationModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        recipient_type=recipient_type,
        recipient_user_id=None if is_passenger else recipient_id,
        recipient_passenger_identity_id=recipient_id if is_passenger else None,
        notification_type="personal_document_changed",
        category="document",
        priority="normal",
        title=title_by_role[recipient_type],
        body=body_by_role[recipient_type],
        lock_screen_title=_LOCK_SCREEN_TITLE,
        lock_screen_body=None,
        contains_sensitive_content=True,
        deep_link_path=f"/{route}?trip_id={access.group_id}",
        dedupe_key=_document_change_dedupe_key(
            dedupe_token=dedupe_token,
            recipient_type=recipient_type,
            operation=operation,
        ),
        public_payload={"route": route, "trip_id": str(access.group_id)},
        status="queued",
        available_at=available_at,
        expires_at=expires_at,
    )


def _document_change_dedupe_key(
    *,
    dedupe_token: str,
    recipient_type: str,
    operation: str,
) -> str:
    digest = hashlib.sha256(dedupe_token.encode("utf-8")).hexdigest()
    return f"personal-document:{operation}:{recipient_type}:{digest}"
