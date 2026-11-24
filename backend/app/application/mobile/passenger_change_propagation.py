"""Shared dashboard passenger mutation bridge and public lifecycle APIs."""

from __future__ import annotations

import hashlib as hashlib
import uuid as uuid
from collections.abc import Iterable as Iterable
from collections.abc import Sequence as Sequence
from dataclasses import dataclass as dataclass
from datetime import UTC as UTC
from datetime import datetime as datetime
from typing import Literal as Literal

from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.application.mobile.coordinator_roster_revision import (
    coordinator_roster_revision as coordinator_roster_revision,
)
from app.application.mobile.notification_service import (
    enqueue_personal_document_change_notifications as enqueue_personal_document_change_notifications,
)
from app.application.mobile.passenger_change_contracts import (
    _PASSENGER_CHANGE_ID_NAMESPACE as _PASSENGER_CHANGE_ID_NAMESPACE,
)
from app.application.mobile.passenger_change_contracts import (
    _TARGETED_COORDINATOR_CHANGE_LIMIT as _TARGETED_COORDINATOR_CHANGE_LIMIT,
)
from app.application.mobile.passenger_change_contracts import (
    _TARGETED_IDENTITY_CHANGE_LIMIT as _TARGETED_IDENTITY_CHANGE_LIMIT,
)
from app.application.mobile.passenger_change_contracts import (
    MobilePassengerChangeEvent as MobilePassengerChangeEvent,
)
from app.application.mobile.passenger_change_contracts import (
    MobilePassengerChangeKind as MobilePassengerChangeKind,
)
from app.application.mobile.passenger_change_contracts import (
    MobilePassengerPropagationResult as MobilePassengerPropagationResult,
)
from app.application.mobile.passenger_change_events import (
    _passenger_change_event_id as _passenger_change_event_id,
)
from app.application.mobile.passenger_change_events import (
    plan_mobile_passenger_change_events as plan_mobile_passenger_change_events,
)
from app.application.mobile.passenger_change_identities import prepare_passenger_change_identities
from app.application.mobile.passenger_change_journal import (
    append_passenger_change_events,
    filter_existing_passenger_change_events,
)
from app.application.mobile.passenger_identity_reconciliation import (
    PassengerIdentityReconciliationResult as PassengerIdentityReconciliationResult,
)
from app.application.mobile.passenger_identity_reconciliation import (
    reconcile_passenger_identities as reconcile_passenger_identities,
)
from app.application.mobile.passenger_identity_reconciliation import (
    reconcile_passenger_identities_for_changes as reconcile_passenger_identities_for_changes,
)
from app.application.mobile.sync_journal import SyncOperation as SyncOperation
from app.application.mobile.sync_journal import (
    append_mobile_sync_change as append_mobile_sync_change,
)
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel as GCGroupAccessModel
from app.infrastructure.database.gc_mobile_models import (
    MobilePassengerIdentityModel as MobilePassengerIdentityModel,
)
from app.infrastructure.database.gc_mobile_models import (
    MobileSyncChangeModel as MobileSyncChangeModel,
)
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel as ClientGroupWhatsAppBroadcastLinkModel,
)
from app.infrastructure.whatsapp.source_group_sync import (
    sync_group_broadcast_contacts as sync_group_broadcast_contacts,
)


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
    sync_broadcast_contacts: bool = False,
) -> MobilePassengerPropagationResult:
    """Reconcile and publish one passenger mutation in the caller's transaction.

    Source-linked WhatsApp contacts follow roster changes independently of GC
    App. The mobile journal remains a no-op for groups without GC App enabled.
    It never serializes passenger fields into the journal.
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
        sync_broadcast_contacts,
    )
    propagated = session.info.setdefault("mobile_passenger_propagation", set())
    await session.flush()
    if change_kind == "profile" or sync_broadcast_contacts:
        await sync_group_broadcast_contacts(
            session,
            agency_id=agency_id,
            group_id=group_id,
            actor_user_id=actor_user_id,
        )
    if dedupe_key in propagated:
        return MobilePassengerPropagationResult(
            enabled=True,
            identity_reconciliation=None,
            sync_changes=0,
        )
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
    prepared = await prepare_passenger_change_identities(
        session,
        access=access,
        agency_id=agency_id,
        group_id=group_id,
        passenger_ids=passenger_ids,
        actor_user_id=actor_user_id,
        operation=operation,
        change_kind=change_kind,
        reconcile_identities=reconcile_identities,
    )
    identity_result = prepared.identity_result
    identities = prepared.identities
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
        event_rows = await filter_existing_passenger_change_events(
            session,
            access=access,
            agency_id=agency_id,
            event_rows=event_rows,
        )
        if not event_rows:
            propagated.add(dedupe_key)
            return MobilePassengerPropagationResult(
                enabled=True,
                identity_reconciliation=identity_result,
                sync_changes=0,
            )
    push_notifications = await append_passenger_change_events(
        session,
        access=access,
        agency_id=agency_id,
        group_id=group_id,
        actor_user_id=actor_user_id,
        previous_manifest_version=previous_manifest_version,
        event_rows=event_rows,
        operation=operation,
        change_kind=change_kind,
        propagation_key=propagation_key,
    )
    propagated.add(dedupe_key)
    return MobilePassengerPropagationResult(
        enabled=True,
        identity_reconciliation=identity_result,
        sync_changes=len(event_rows),
        push_notifications=push_notifications,
    )


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
                        select(ClientGroupWhatsAppBroadcastLinkModel.client_group_id).where(
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
