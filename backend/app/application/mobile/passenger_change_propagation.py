"""Propagate authoritative passenger mutations into the compact mobile journal.

Legacy passport, WhatsApp, and document-distribution workflows remain the
source of truth.  This module is the narrow bridge that lets those workflows
reconcile mobile identities and announce only the affected mobile resources
inside the caller's existing transaction.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.coordinator_roster_revision import (
    coordinator_roster_revision,
)
from app.application.mobile.notification_service import (
    enqueue_personal_document_change_notifications,
)
from app.application.mobile.passenger_identity_reconciliation import (
    PassengerIdentityReconciliationResult,
    reconcile_passenger_identities,
    reconcile_passenger_identities_for_changes,
)
from app.application.mobile.sync_journal import SyncOperation, append_mobile_sync_change
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
    MobileSyncChangeModel,
)
from app.infrastructure.database.models import ClientGroupWhatsAppBroadcastLinkModel

MobilePassengerChangeKind = Literal["profile", "documents"]
_TARGETED_COORDINATOR_CHANGE_LIMIT = 100
_TARGETED_IDENTITY_CHANGE_LIMIT = 8
_PASSENGER_CHANGE_ID_NAMESPACE = uuid.UUID("9f5c33ec-0705-456b-b01a-31f0889464d7")


@dataclass(frozen=True, slots=True)
class MobilePassengerChangeEvent:
    audience: Literal["passenger", "client_manager", "coordinator"]
    passenger_identity_id: uuid.UUID | None
    entity_type: str
    entity_id: uuid.UUID | None
    operation: SyncOperation
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class MobilePassengerPropagationResult:
    enabled: bool
    identity_reconciliation: PassengerIdentityReconciliationResult | None
    sync_changes: int
    push_notifications: int = 0


def plan_mobile_passenger_change_events(
    *,
    group_id: uuid.UUID,
    passenger_submission_ids: Sequence[uuid.UUID],
    passenger_identities: Sequence[tuple[uuid.UUID, uuid.UUID]],
    operation: Literal["upsert", "delete"],
    change_kind: MobilePassengerChangeKind,
    passenger_access_enabled: bool,
    client_manager_access_enabled: bool,
    coordinator_access_enabled: bool,
) -> tuple[MobilePassengerChangeEvent, ...]:
    """Build PII-free, bounded journal events for one tenant-scoped group."""

    passenger_ids = tuple(sorted(set(passenger_submission_ids), key=str))
    events: list[MobilePassengerChangeEvent] = []

    if coordinator_access_enabled and passenger_ids:
        if len(passenger_ids) <= _TARGETED_COORDINATOR_CHANGE_LIMIT:
            events.extend(
                MobilePassengerChangeEvent(
                    audience="coordinator",
                    passenger_identity_id=None,
                    entity_type="coordinator_passenger",
                    entity_id=passenger_id,
                    operation=operation,
                    payload={
                        "resource_path": (
                            f"/api/v1/mobile/coordinator/groups/{group_id}/"
                            f"passengers/{passenger_id}"
                        )
                    },
                )
                for passenger_id in passenger_ids
            )
        else:
            events.append(
                MobilePassengerChangeEvent(
                    audience="coordinator",
                    passenger_identity_id=None,
                    entity_type="passenger_roster",
                    entity_id=None,
                    operation=operation,
                    payload={
                        "resource_path": (
                            f"/api/v1/mobile/coordinator/groups/{group_id}/passengers"
                        )
                    },
                )
            )

    if client_manager_access_enabled and passenger_ids:
        events.append(
            MobilePassengerChangeEvent(
                audience="client_manager",
                passenger_identity_id=None,
                entity_type="passenger_readiness",
                entity_id=None,
                operation="upsert",
                payload={
                    "resource_path": (
                        f"/api/v1/mobile/manager/groups/{group_id}/readiness"
                    )
                },
            )
        )

    if passenger_access_enabled and (
        operation == "upsert" or change_kind == "documents"
    ):
        entity_type = (
            "personal_document" if change_kind == "documents" else "passenger_profile"
        )
        resource_name = "documents" if change_kind == "documents" else "manifest"
        for identity_id, passenger_id in sorted(
            set(passenger_identities), key=lambda item: (str(item[0]), str(item[1]))
        ):
            if passenger_id not in passenger_ids:
                continue
            events.append(
                MobilePassengerChangeEvent(
                    audience="passenger",
                    passenger_identity_id=identity_id,
                    entity_type=entity_type,
                    entity_id=passenger_id,
                    operation=operation,
                    payload={
                        "resource_path": (
                            f"/api/v1/mobile/trips/{group_id}/{resource_name}"
                        )
                    },
                )
            )

    return tuple(events)


async def propagate_mobile_passenger_change(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    passenger_submission_ids: Iterable[uuid.UUID],
    actor_user_id: uuid.UUID | None,
    operation: Literal["upsert", "delete"] = "upsert",
    change_kind: MobilePassengerChangeKind = "profile",
    reconcile_identities: bool = True,
    propagation_key: str | None = None,
) -> MobilePassengerPropagationResult:
    """Reconcile and publish one passenger mutation in the caller's transaction.

    The helper is deliberately a no-op unless the exact tenant/group is enabled
    in GC App.  It never serializes passenger fields into the journal.
    """

    passenger_ids = tuple(sorted(set(passenger_submission_ids), key=str))
    dedupe_key = (
        "mobile-passenger-change",
        agency_id,
        group_id,
        passenger_ids,
        operation,
        change_kind,
        reconcile_identities,
        propagation_key,
    )
    propagated = session.info.setdefault("mobile_passenger_propagation", set())
    if dedupe_key in propagated:
        return MobilePassengerPropagationResult(
            enabled=True,
            identity_reconciliation=None,
            sync_changes=0,
        )

    await session.flush()
    access = (
        await session.execute(
            select(GCGroupAccessModel)
            .where(
                GCGroupAccessModel.agency_id == agency_id,
                GCGroupAccessModel.group_id == group_id,
                GCGroupAccessModel.is_enabled.is_(True),
                GCGroupAccessModel.revoked_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if access is None:
        propagated.add(dedupe_key)
        return MobilePassengerPropagationResult(
            enabled=False,
            identity_reconciliation=None,
            sync_changes=0,
        )

    previous_manifest_version = access.manifest_version
    identity_result: PassengerIdentityReconciliationResult | None = None
    if (
        reconcile_identities
        and change_kind == "profile"
        and access.passenger_access_enabled
    ):
        if 0 < len(passenger_ids) <= _TARGETED_IDENTITY_CHANGE_LIMIT:
            identity_result = await reconcile_passenger_identities_for_changes(
                session,
                access=access,
                actor_user_id=actor_user_id,
                passenger_submission_ids=passenger_ids,
            )
        else:
            identity_result = await reconcile_passenger_identities(
                session,
                access=access,
                actor_user_id=actor_user_id,
            )

    identities: list[tuple[uuid.UUID, uuid.UUID]] = []
    if (
        passenger_ids
        and access.passenger_access_enabled
        and (operation == "upsert" or change_kind == "documents")
    ):
        identity_rows = (
            await session.execute(
                select(
                    MobilePassengerIdentityModel.id,
                    MobilePassengerIdentityModel.passenger_submission_id,
                ).where(
                    MobilePassengerIdentityModel.agency_id == agency_id,
                    MobilePassengerIdentityModel.group_id == group_id,
                    MobilePassengerIdentityModel.gc_group_access_id == access.id,
                    MobilePassengerIdentityModel.passenger_submission_id.in_(passenger_ids),
                    MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                    MobilePassengerIdentityModel.revoked_at.is_(None),
                )
            )
        ).all()
        identities = [
            (identity_id, passenger_submission_id)
            for identity_id, passenger_submission_id in identity_rows
        ]

    events = plan_mobile_passenger_change_events(
        group_id=group_id,
        passenger_submission_ids=passenger_ids,
        passenger_identities=identities,
        operation=operation,
        change_kind=change_kind,
        passenger_access_enabled=access.passenger_access_enabled,
        client_manager_access_enabled=access.client_manager_access_enabled,
        coordinator_access_enabled=access.coordinator_access_enabled,
    )
    if not events:
        propagated.add(dedupe_key)
        return MobilePassengerPropagationResult(
            enabled=True,
            identity_reconciliation=identity_result,
            sync_changes=0,
        )

    event_rows: list[tuple[MobilePassengerChangeEvent, uuid.UUID | None]] = [
        (event, None) for event in events
    ]
    if propagation_key is not None:
        event_rows = [
            (
                event,
                _passenger_change_event_id(
                    propagation_key=propagation_key,
                    group_id=group_id,
                    event=event,
                ),
            )
            for event in events
        ]
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
            (event, change_id)
            for event, change_id in event_rows
            if change_id not in existing_ids
        ]
        if not event_rows:
            propagated.add(dedupe_key)
            return MobilePassengerPropagationResult(
                enabled=True,
                identity_reconciliation=identity_result,
                sync_changes=0,
            )

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
                or (
                    f"{group_id}:manifest:{access.manifest_version}:"
                    f"{operation}:documents"
                )
            ),
        )
        push_notifications = notification_counts.total
    propagated.add(dedupe_key)
    return MobilePassengerPropagationResult(
        enabled=True,
        identity_reconciliation=identity_result,
        sync_changes=len(event_rows),
        push_notifications=push_notifications,
    )


def _passenger_change_event_id(
    *,
    propagation_key: str,
    group_id: uuid.UUID,
    event: MobilePassengerChangeEvent,
) -> uuid.UUID:
    """Derive a PII-free durable id so worker retries cannot append twice."""

    source_digest = hashlib.sha256(propagation_key.encode("utf-8")).hexdigest()
    event_scope = ":".join(
        (
            source_digest,
            str(group_id),
            event.audience,
            str(event.passenger_identity_id or "group"),
            event.entity_type,
            str(event.entity_id or "collection"),
            event.operation,
        )
    )
    return uuid.uuid5(_PASSENGER_CHANGE_ID_NAMESPACE, event_scope)


async def reconcile_mobile_passenger_access_for_group(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
) -> PassengerIdentityReconciliationResult | None:
    """Reconcile one enabled passenger-access group after identity-source edits."""

    dedupe_key = ("mobile-passenger-reconcile", agency_id, group_id)
    propagated = session.info.setdefault("mobile_passenger_propagation", set())
    if dedupe_key in propagated:
        return None
    await session.flush()
    access = (
        await session.execute(
            select(GCGroupAccessModel)
            .where(
                GCGroupAccessModel.agency_id == agency_id,
                GCGroupAccessModel.group_id == group_id,
                GCGroupAccessModel.is_enabled.is_(True),
                GCGroupAccessModel.passenger_access_enabled.is_(True),
                GCGroupAccessModel.revoked_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if access is None:
        propagated.add(dedupe_key)
        return None
    result = await reconcile_passenger_identities(
        session,
        access=access,
        actor_user_id=actor_user_id,
    )
    propagated.add(dedupe_key)
    return result


async def reconcile_mobile_passenger_access_for_broadcast(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    broadcast_group_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
) -> int:
    """Reconcile all explicitly linked GC groups after a recipient mutation."""

    await session.flush()
    group_ids = tuple(
        sorted(
            set(
                (
                    await session.execute(
                        select(
                            ClientGroupWhatsAppBroadcastLinkModel.client_group_id
                        ).where(
                            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
                            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id
                            == broadcast_group_id,
                        )
                    )
                ).scalars()
            ),
            key=str,
        )
    )
    reconciled = 0
    for group_id in group_ids:
        result = await reconcile_mobile_passenger_access_for_group(
            session,
            agency_id=agency_id,
            group_id=group_id,
            actor_user_id=actor_user_id,
        )
        reconciled += int(result is not None)
    return reconciled
