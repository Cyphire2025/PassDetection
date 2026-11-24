"""Preserve durable replay, version fencing and ordered journal/notification writes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.coordinator_roster_revision import coordinator_roster_revision
from app.application.mobile.notification_service import (
    enqueue_personal_document_change_notifications,
)
from app.application.mobile.passenger_change_contracts import (
    MobilePassengerChangeEvent,
    MobilePassengerChangeKind,
)
from app.application.mobile.sync_journal import append_mobile_sync_change
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel, MobileSyncChangeModel


async def filter_existing_passenger_change_events(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    agency_id: uuid.UUID,
    event_rows: list[tuple[MobilePassengerChangeEvent, uuid.UUID | None]],
) -> list[tuple[MobilePassengerChangeEvent, uuid.UUID | None]]:
    change_ids = [change_id for _event, change_id in event_rows if change_id]
    existing_ids = set(
        (
            await session.execute(
                select(MobileSyncChangeModel.id).where(
                    MobileSyncChangeModel.id.in_(change_ids),
                    MobileSyncChangeModel.agency_id == agency_id,
                    MobileSyncChangeModel.gc_group_access_id == access.id,
                )
            )
        ).scalars()
    )
    event_rows = [
        (event, change_id) for event, change_id in event_rows if change_id not in existing_ids
    ]
    return event_rows


async def append_passenger_change_events(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    previous_manifest_version: int,
    event_rows: list[tuple[MobilePassengerChangeEvent, uuid.UUID | None]],
    operation: Literal["upsert", "delete"],
    change_kind: MobilePassengerChangeKind,
    propagation_key: str | None,
) -> int:
    now = datetime.now(tz=UTC)
    if access.manifest_version == previous_manifest_version:
        access.manifest_version += 1
        access.revision += 1
        access.updated_at = now
        if actor_user_id is not None:
            access.updated_by_user_id = actor_user_id
    await session.flush()
    coordinator_revision: int | None = None
    if any(event.entity_type == "coordinator_passenger" for event, _ in event_rows):
        coordinator_revision = await coordinator_roster_revision(
            session,
            agency_id=agency_id,
            group_id=group_id,
        )
    for event, change_id in event_rows:
        payload = dict(event.payload)
        if event.entity_type == "coordinator_passenger":
            # The client accepts this bounded delta only when the event-time
            # authoritative revision equals the manifest revision.  Any
            # concurrent/un-journaled roster mutation therefore fails closed
            # to the existing full roster reconciliation.
            payload["roster_revision"] = coordinator_revision or 0
        await append_mobile_sync_change(
            session,
            access=access,
            change_id=change_id,
            audience=event.audience,
            passenger_identity_id=event.passenger_identity_id,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            operation=event.operation,
            version=access.manifest_version,
            changed_by_user_id=actor_user_id,
            payload=payload,
        )
    push_notifications = 0
    if change_kind == "documents":
        notification_counts = await enqueue_personal_document_change_notifications(
            session,
            access=access,
            passenger_identity_ids=[
                event.passenger_identity_id
                for event, _change_id in event_rows
                if event.passenger_identity_id is not None
            ],
            operation=operation,
            dedupe_token=(
                propagation_key
                or (f"{group_id}:manifest:{access.manifest_version}:{operation}:documents")
            ),
        )
        push_notifications = notification_counts.total
    return push_notifications
