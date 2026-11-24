"""Pure role-scoped event planning and stable source-event identifiers."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from typing import Literal

from app.application.mobile.passenger_change_contracts import (
    _PASSENGER_CHANGE_ID_NAMESPACE,
    _TARGETED_COORDINATOR_CHANGE_LIMIT,
    MobilePassengerChangeEvent,
    MobilePassengerChangeKind,
)


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
                payload={"resource_path": (f"/api/v1/mobile/manager/groups/{group_id}/readiness")},
            )
        )

    if passenger_access_enabled and (operation == "upsert" or change_kind == "documents"):
        entity_type = "personal_document" if change_kind == "documents" else "passenger_profile"
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
                    payload={"resource_path": (f"/api/v1/mobile/trips/{group_id}/{resource_name}")},
                )
            )

    return tuple(events)


plan_mobile_passenger_change_events.__module__ = (
    "app.application.mobile.passenger_change_propagation"
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


_passenger_change_event_id.__module__ = "app.application.mobile.passenger_change_propagation"
