"""Transaction-safe, PII-free invalidation hints for mobile realtime.

The append-only SQL journal is the source of truth.  This module observes only
successful outer commits and hands a compact, lossy hint to the process-local
realtime hub.  Redis failures can therefore delay freshness, but can never
roll back or corrupt an authoritative dashboard write.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal, cast

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.core.logging.logger import get_logger
from app.infrastructure.database.gc_mobile_models import MobileSyncChangeModel

MobileRealtimeInvalidation = Literal[
    "all",
    "announcements",
    "attendance",
    "documents",
    "itinerary",
    "operations",
    "roster",
]


@dataclass(frozen=True, slots=True)
class MobileRealtimeHint:
    """Minimal internal fanout envelope.

    ``agency_id`` is used only by the server-side tenant index and is removed
    before delivery to a phone. No entity identifier, file identifier, token,
    name, message body, or journal payload crosses this boundary.
    """

    agency_id: uuid.UUID
    trip_id: uuid.UUID
    cursor: int
    invalidation: MobileRealtimeInvalidation

    def redis_payload(self) -> dict[str, str | int]:
        return {
            "v": 1,
            "agency_id": str(self.agency_id),
            "trip_id": str(self.trip_id),
            "cursor": self.cursor,
            "invalidation": self.invalidation,
        }

    def client_payload(self) -> dict[str, str | int]:
        return {
            "type": "sync_hint",
            "trip_id": str(self.trip_id),
            "cursor": self.cursor,
            "invalidation": self.invalidation,
        }


MobileRealtimePublisher = Callable[[tuple[MobileRealtimeHint, ...]], None]

_PENDING_KEY: Final = "mobile_realtime_pending_changes"
_publisher: MobileRealtimePublisher | None = None
logger = get_logger(__name__)


def invalidation_for_entity_type(entity_type: str) -> MobileRealtimeInvalidation:
    normalized = entity_type.strip().casefold()
    if normalized == "announcement":
        return "announcements"
    if normalized == "itinerary":
        return "itinerary"
    if normalized.startswith("common_document") or normalized.endswith("document"):
        return "documents"
    if normalized in {
        "coordinator_passenger",
        "passenger",
        "passenger_identity",
        "roster",
    }:
        return "roster"
    if normalized.startswith("attendance"):
        return "attendance"
    if normalized in {"incident", "readiness"}:
        return "operations"
    return "all"


def stage_mobile_realtime_change(
    session: object,
    change: MobileSyncChangeModel,
) -> None:
    """Attach one journal model to its owning SQLAlchemy transaction.

    The model itself is retained until ``after_commit`` because batched callers
    may request ``flush=False``; SQLAlchemy assigns their monotonic sequences
    during the later shared flush.
    """

    sync_session = getattr(session, "sync_session", session)
    if not isinstance(sync_session, Session):
        # Test doubles and non-SQLAlchemy adapters retain their existing
        # behavior. The durable cursor still guarantees correctness.
        return
    pending = cast(
        list[MobileSyncChangeModel],
        sync_session.info.setdefault(_PENDING_KEY, []),
    )
    pending.append(change)


def register_mobile_realtime_publisher(
    publisher: MobileRealtimePublisher,
) -> Callable[[], None]:
    """Install the single process-local, non-blocking post-commit sink."""

    global _publisher
    _publisher = publisher

    def unregister() -> None:
        global _publisher
        if _publisher is publisher:
            _publisher = None

    return unregister


def _committed_hints(session: Session) -> tuple[MobileRealtimeHint, ...]:
    changes = cast(
        list[MobileSyncChangeModel],
        session.info.pop(_PENDING_KEY, []),
    )
    coalesced: dict[tuple[uuid.UUID, uuid.UUID], MobileRealtimeHint] = {}
    for change in changes:
        state = inspect(change)
        # A model rolled back inside a savepoint must not produce a hint when
        # the surrounding transaction later commits.
        if not state.persistent:
            continue
        cursor = change.sequence
        if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 1:
            continue
        candidate = MobileRealtimeHint(
            agency_id=change.agency_id,
            trip_id=change.group_id,
            cursor=cursor,
            invalidation=invalidation_for_entity_type(change.entity_type),
        )
        key = (candidate.agency_id, candidate.trip_id)
        previous = coalesced.get(key)
        if previous is None:
            coalesced[key] = candidate
            continue
        coalesced[key] = MobileRealtimeHint(
            agency_id=candidate.agency_id,
            trip_id=candidate.trip_id,
            cursor=max(previous.cursor, candidate.cursor),
            invalidation=(
                previous.invalidation if previous.invalidation == candidate.invalidation else "all"
            ),
        )
    return tuple(coalesced.values())


@event.listens_for(Session, "after_commit")
def _publish_after_commit(session: Session) -> None:
    # SQLAlchemy fires ``after_commit`` for a released SAVEPOINT as well as for
    # the root transaction. Retain staged rows until the root commit; otherwise
    # a later outer rollback could leave clients chasing a cursor that never
    # became durable.
    if session.in_nested_transaction():
        return
    hints = _committed_hints(session)
    publisher = _publisher
    if not hints or publisher is None:
        return
    try:
        # The registered hub only performs bounded put_nowait operations here.
        # Redis network I/O happens in a separate task after the DB commit has
        # already succeeded.
        publisher(hints)
    except Exception as exc:  # pragma: no cover - defensive plugin boundary
        logger.warning(
            "mobile_realtime_post_commit_publish_failed",
            error_type=type(exc).__name__,
            hint_count=len(hints),
        )


@event.listens_for(Session, "after_rollback")
def _discard_after_rollback(session: Session) -> None:
    # A SAVEPOINT rollback must not discard rows staged earlier by its still
    # active parent transaction. Rolled-back inserts become non-persistent and
    # are filtered by ``_committed_hints`` when that parent later commits.
    if session.in_nested_transaction():
        return
    # Dropping a hint is safe: the next foreground/fallback cursor pass finds
    # every committed row. Publishing a rolled-back hint would be needless
    # noise, so rollback always clears the bounded staging list.
    session.info.pop(_PENDING_KEY, None)


__all__ = [
    "MobileRealtimeHint",
    "MobileRealtimeInvalidation",
    "invalidation_for_entity_type",
    "register_mobile_realtime_publisher",
    "stage_mobile_realtime_change",
]
