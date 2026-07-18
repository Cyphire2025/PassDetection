"""Low-cardinality, cross-process travel-flow event metrics.

Only fixed event/reason pairs are accepted. Callers cannot turn traveller
values, upload-link tokens, document numbers, exception text, or arbitrary
client strings into metric labels.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Protocol

from app.core.logging.logger import get_logger
from app.infrastructure.observability.metrics import MetricsRegistry, metrics

logger = get_logger(__name__)


class OperationalEvent(str, Enum):
    UPLOAD_RESULT = "upload_result"
    DOCUMENT_CLASSIFICATION = "document_classification"
    POST_SUBMISSION_VERIFICATION = "post_submission_verification"
    STAFF_APPROVAL = "staff_approval"
    RATE_LIMIT = "rate_limit"
    VISA_PHOTO_REJECTION = "visa_photo_rejection"
    PASSPORT_SCANNER_REJECTION = "passport_scanner_rejection"
    PUBLIC_FLOW = "public_flow"


_ALLOWED_REASONS: dict[OperationalEvent, frozenset[str]] = {
    OperationalEvent.UPLOAD_RESULT: frozenset(
        {
            "success",
            "idempotent_replay",
            "reconciled",
            "reconcile_miss",
            "read_error",
            "validation_failed",
            "storage_failed",
            "database_failed",
            "domain_rejected",
            "unexpected_failure",
        }
    ),
    OperationalEvent.DOCUMENT_CLASSIFICATION: frozenset(
        {
            "accepted",
            "passport_cover",
            "wrong_passport_page",
            "wrong_document",
            "document_low_quality",
            "document_unreadable",
            "document_uncertain",
            "provider_unavailable",
        }
    ),
    OperationalEvent.POST_SUBMISSION_VERIFICATION: frozenset(
        {
            "ai_approved",
            "needs_review",
            "stale_result",
            "storage_unavailable",
            "provider_unavailable",
            "internal_error",
        }
    ),
    OperationalEvent.STAFF_APPROVAL: frozenset(
        {
            "approved",
            "already_approved",
            "stale",
            "unavailable",
            "forbidden",
            "not_found",
            "unexpected_failure",
        }
    ),
    OperationalEvent.RATE_LIMIT: frozenset(
        {
            "app_api",
            "upload_bootstrap_session",
            "upload_bootstrap_aggregate",
            "upload_session",
            "upload_aggregate",
            "rate_limit_backend_unavailable",
        }
    ),
    OperationalEvent.VISA_PHOTO_REJECTION: frozenset(
        {
            "no_face",
            "multiple_faces",
            "too_far",
            "too_close",
            "off_center",
            "head_tilt",
            "eyewear_detected",
            "eyewear_uncertain",
            "too_dark",
            "too_bright",
            "blurry",
            "background_not_light_neutral",
            "background_not_plain",
            "camera_unavailable",
            "quality_model_unavailable",
        }
    ),
    OperationalEvent.PASSPORT_SCANNER_REJECTION: frozenset(
        {
            "no_document",
            "incomplete_document",
            "too_small",
            "sideways",
            "upside_down",
            "excessive_skew",
            "multiple_documents",
            "screen_or_book",
            "missing_mrz",
            "not_passport_page",
            "glare",
            "too_dark",
            "too_bright",
            "blurry",
            "camera_unavailable",
            "crop_validation_failed",
        }
    ),
    OperationalEvent.PUBLIC_FLOW: frozenset(
        {
            "connectivity_lost",
            "connectivity_restored",
            "camera_cancelled",
            "upload_abandoned",
            "recovery_started",
            "recovery_succeeded",
            "recovery_missed",
        }
    ),
}
PUBLIC_OPERATIONAL_EVENTS = frozenset(
    {
        OperationalEvent.VISA_PHOTO_REJECTION,
        OperationalEvent.PASSPORT_SCANNER_REJECTION,
        OperationalEvent.PUBLIC_FLOW,
    }
)


def is_allowed_operational_reason(
    event: OperationalEvent,
    reason: str,
) -> bool:
    return reason.strip().lower().replace("-", "_") in _ALLOWED_REASONS[event]


def parse_public_operational_event(value: str) -> OperationalEvent | None:
    try:
        event = OperationalEvent(value.strip().lower())
    except ValueError:
        return None
    return event if event in PUBLIC_OPERATIONAL_EVENTS else None


class _SharedCounterStore(Protocol):
    def increment(self, name: str, amount: int = 1) -> None: ...


class OperationalEventMetrics:
    """Write fixed event counters locally and to the shared Redis adapter."""

    def __init__(
        self,
        *,
        registry: MetricsRegistry = metrics,
        shared_store: _SharedCounterStore | None = None,
    ) -> None:
        self._registry = registry
        if shared_store is None:
            # Lazy import avoids coupling the base in-process registry to the
            # AI scheduler module during application import.
            from app.infrastructure.ai_priority.metrics import (
                get_shared_ai_priority_metrics_store,
            )

            shared_store = get_shared_ai_priority_metrics_store()
        self._shared = shared_store

    def record(
        self,
        event: OperationalEvent,
        reason: str,
        *,
        amount: int = 1,
    ) -> None:
        if amount < 1:
            raise ValueError("Operational metric amount must be positive")
        normalized_reason = reason.strip().lower().replace("-", "_")
        if normalized_reason not in _ALLOWED_REASONS[event]:
            normalized_reason = "other"
        total_name = f"travel_flow.events.total.{event.value}"
        reason_name = (
            f"travel_flow.events.reason.{event.value}.{normalized_reason}"
        )
        self._registry.increment(total_name, amount)
        self._registry.increment(reason_name, amount)
        try:
            self._shared.increment(total_name, amount)
            self._shared.increment(reason_name, amount)
        except Exception as exc:
            # Metrics must never change the workflow outcome. The local
            # aggregate remains available, and the failure is privacy-safe.
            logger.warning(
                "operational_metrics_shared_write_failed",
                error_type=type(exc).__name__,
            )


@lru_cache(maxsize=1)
def get_operational_event_metrics() -> OperationalEventMetrics:
    return OperationalEventMetrics()


def record_operational_event(
    event: OperationalEvent,
    reason: str,
    *,
    amount: int = 1,
) -> None:
    """Best-effort convenience hook for request and worker boundaries."""

    try:
        get_operational_event_metrics().record(
            event,
            reason,
            amount=amount,
        )
    except Exception as exc:
        logger.warning(
            "operational_metrics_record_failed",
            event=event.value,
            error_type=type(exc).__name__,
        )
