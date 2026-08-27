"""Privacy-safe, bounded operational metrics for My Photos.

Metric dimensions are intentionally represented by closed vocabularies in the
metric name. Callers cannot attach tenant, passenger, asset, provider-session,
storage-reference, or delivery-URL values.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal

from app.infrastructure.observability.metrics import MetricsRegistry, metrics

Operation = Literal["summary", "page", "download_authorization"]
Outcome = Literal["success", "error"]
ProviderCategory = Literal["unavailable", "throttled"]
JobOutcome = Literal[
    "claimed",
    "redelivered",
    "lease_busy",
    "lease_lost",
    "retrying",
    "succeeded",
    "failed",
    "cancelled",
]
QueueKind = Literal["index", "media", "search"]
PreparationOutcome = Literal["available", "waiting", "failed"]
PaginationError = Literal["invalid", "stale"]
RedeliveryKind = Literal["index", "media", "refresh", "search"]
DispatchOutcome = Literal["published", "recovery_pending"]


class MyPhotosMetrics:
    """A narrow adapter that prevents cardinality and biometric-data leaks."""

    def __init__(self, registry: MetricsRegistry = metrics) -> None:
        self._registry = registry

    @contextmanager
    def api_timer(self, operation: Operation) -> Iterator[None]:
        started = time.perf_counter()
        outcome: Outcome = "error"
        try:
            yield
            outcome = "success"
        finally:
            self._registry.increment(f"my_photos.api.{operation}.{outcome}")
            self._registry.observe(
                f"my_photos.api.{operation}.duration_ms",
                (time.perf_counter() - started) * 1_000,
            )

    def gallery_state(self, state: str) -> None:
        safe = state if state in _GALLERY_STATES else "unknown"
        self._registry.increment(f"my_photos.gallery.state.{safe}")

    def authorization(self, *, allowed: bool) -> None:
        self._registry.increment(f"my_photos.authorization.{'allowed' if allowed else 'denied'}")

    def provider(self, category: ProviderCategory) -> None:
        self._registry.increment(f"my_photos.provider.{category}")

    def search_finished(self, *, outcome: str, duration_ms: float) -> None:
        safe = outcome if outcome in _SEARCH_OUTCOMES else "failed"
        self._registry.increment(f"my_photos.search.{safe}")
        self._registry.observe("my_photos.search.duration_ms", max(0.0, duration_ms))

    def job(self, outcome: JobOutcome) -> None:
        self._registry.increment(f"my_photos.job.{outcome}")

    def rehydration_requested(self) -> None:
        self._registry.increment("my_photos.media.rehydration_requested")

    def queue_depth(self, kind: QueueKind, depth: int) -> None:
        self._registry.set_gauge(f"my_photos.queue.{kind}.depth", float(max(0, depth)))

    def indexing_assets(self, *, succeeded: int, failed: int) -> None:
        if succeeded > 0:
            self._registry.increment("my_photos.index.assets.succeeded", succeeded)
        if failed > 0:
            self._registry.increment("my_photos.index.assets.failed", failed)

    def face_occurrences(self, count: int) -> None:
        if count > 0:
            self._registry.increment("my_photos.index.face_occurrences", count)

    def preparation_finished(self, *, outcome: PreparationOutcome, duration_ms: float) -> None:
        self._registry.increment(f"my_photos.preparation.{outcome}")
        self._registry.observe("my_photos.preparation.duration_ms", max(0.0, duration_ms))

    def pagination_error(self, category: PaginationError) -> None:
        self._registry.increment(f"my_photos.pagination.{category}")

    def idempotent_redelivery(self, kind: RedeliveryKind) -> None:
        self._registry.increment(f"my_photos.redelivery.{kind}")

    def dispatch(self, outcome: DispatchOutcome) -> None:
        self._registry.increment(f"my_photos.dispatch.{outcome}")


_GALLERY_STATES = frozenset(
    {
        "not_uploaded",
        "awaiting_upload",
        "processing",
        "indexing",
        "ready",
        "failed",
        "removed",
    }
)
_SEARCH_OUTCOMES = frozenset({"complete", "no_matches", "retrying", "failed", "cancelled"})

my_photos_metrics = MyPhotosMetrics()


__all__ = ["MyPhotosMetrics", "my_photos_metrics"]
