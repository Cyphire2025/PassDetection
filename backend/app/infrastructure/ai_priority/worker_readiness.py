"""Bounded, queue-specific Celery worker readiness.

Celery inspection is a broker round trip, so the API never performs it for
every readiness request. Each API process keeps a short, thread-safe cache and
uses one bounded ``active_queues`` broadcast when the cache expires.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.core.config.settings import Settings
from app.core.logging.logger import get_logger
from app.infrastructure.ai_priority import EXTRACTION_QUEUE, VERIFICATION_QUEUE

logger = get_logger(__name__)


@dataclass(frozen=True)
class CeleryQueueSnapshot:
    available_queues: frozenset[str]
    control_reachable: bool


QueueQuery = Callable[[float], CeleryQueueSnapshot]


class CachedCeleryQueueProbe:
    """Serialize and cache a bounded Celery control query."""

    def __init__(
        self,
        *,
        query: QueueQuery | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._query = query or _query_active_queues
        self._clock = clock
        self._lock = threading.Lock()
        self._expires_at = 0.0
        self._cached = CeleryQueueSnapshot(
            available_queues=frozenset(),
            control_reachable=False,
        )

    def snapshot(
        self,
        *,
        timeout_seconds: float,
        cache_seconds: float,
    ) -> CeleryQueueSnapshot:
        now = self._clock()
        if now < self._expires_at:
            return self._cached

        with self._lock:
            now = self._clock()
            if now < self._expires_at:
                return self._cached
            try:
                snapshot = self._query(timeout_seconds)
            except Exception as exc:
                logger.warning(
                    "celery_ai_worker_readiness_probe_failed",
                    error_type=type(exc).__name__,
                )
                snapshot = CeleryQueueSnapshot(
                    available_queues=frozenset(),
                    control_reachable=False,
                )
            self._cached = snapshot
            self._expires_at = self._clock() + cache_seconds
            return snapshot


def gemini_worker_readiness(
    settings: Settings,
    *,
    probe: CachedCeleryQueueProbe | None = None,
) -> tuple[dict[str, str], bool]:
    """Return safe worker-queue readiness statuses and their combined gate."""

    if settings.processing_backend != "celery":
        return (
            {
                "celery_worker_control": "not_required_background_backend",
                "gemini_extraction_worker": "not_required_background_backend",
                "gemini_verification_worker": (
                    "not_required_background_backend"
                    if settings.gemini_verification_enabled
                    else "not_required_verification_disabled"
                ),
            },
            True,
        )

    snapshot = (probe or _queue_probe).snapshot(
        timeout_seconds=settings.processing_worker_ping_timeout_seconds,
        cache_seconds=settings.processing_worker_readiness_cache_seconds,
    )
    extraction_ready = EXTRACTION_QUEUE in snapshot.available_queues
    verification_ready = (
        not settings.gemini_verification_enabled
        or VERIFICATION_QUEUE in snapshot.available_queues
    )

    return (
        {
            "celery_worker_control": (
                "reachable" if snapshot.control_reachable else "unreachable"
            ),
            "gemini_extraction_worker": (
                "available" if extraction_ready else "queue_not_consumed"
            ),
            "gemini_verification_worker": (
                "not_required_verification_disabled"
                if not settings.gemini_verification_enabled
                else (
                    "available"
                    if verification_ready
                    else "queue_not_consumed"
                )
            ),
        },
        (
            snapshot.control_reachable
            and extraction_ready
            and verification_ready
        ),
    )


def celery_queue_available(
    queue_name: str,
    *,
    timeout_seconds: float,
) -> bool:
    """Return whether Celery control can see an exact queue consumer."""

    snapshot = _query_active_queues(timeout_seconds)
    return (
        snapshot.control_reachable
        and queue_name in snapshot.available_queues
    )


def _query_active_queues(timeout_seconds: float) -> CeleryQueueSnapshot:
    # Import lazily so non-Celery development/test runtimes can import health
    # routes without requiring the Celery package.
    from app.infrastructure.processing.celery_app import celery_app

    inspector = celery_app.control.inspect(timeout=timeout_seconds)
    replies = inspector.active_queues() or {}
    return CeleryQueueSnapshot(
        available_queues=_queue_names_from_replies(replies),
        control_reachable=bool(replies),
    )


def _queue_names_from_replies(
    replies: Mapping[str, Sequence[Mapping[str, Any]]],
) -> frozenset[str]:
    names: set[str] = set()
    for queues in replies.values():
        if isinstance(queues, (str, bytes)):
            continue
        for queue in queues:
            if not isinstance(queue, Mapping):
                continue
            name = queue.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    return frozenset(names)


# Construct the process-local cache only after its default query helper exists.
_queue_probe = CachedCeleryQueueProbe()
