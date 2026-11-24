"""Stable shared passenger-change DATA and existing policy constants."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from app.application.mobile.passenger_identity_reconciliation import (
    PassengerIdentityReconciliationResult,
)
from app.application.mobile.sync_journal import SyncOperation

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


MobilePassengerChangeEvent.__module__ = "app.application.mobile.passenger_change_propagation"
for _method_name in ("__init__", "__repr__", "__eq__", "__setattr__", "__delattr__", "__hash__"):
    _method = getattr(MobilePassengerChangeEvent, _method_name)
    _method.__module__ = "app.application.mobile.passenger_change_propagation"
    if getattr(_method, "__wrapped__", None) is not None:
        _method.__wrapped__.__module__ = "app.application.mobile.passenger_change_propagation"
del _method_name, _method
MobilePassengerPropagationResult.__module__ = "app.application.mobile.passenger_change_propagation"
for _method_name in ("__init__", "__repr__", "__eq__", "__setattr__", "__delattr__", "__hash__"):
    _method = getattr(MobilePassengerPropagationResult, _method_name)
    _method.__module__ = "app.application.mobile.passenger_change_propagation"
    if getattr(_method, "__wrapped__", None) is not None:
        _method.__wrapped__.__module__ = "app.application.mobile.passenger_change_propagation"
del _method_name, _method
