"""Ordered gallery, enrollment and result state decisions for one passenger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoGalleryModel,
    MyPhotoSearchRunModel,
)
from app.presentation.api.v1.schemas.my_photos_schemas import MyPhotosResultsResponse

_GALLERY_STATES: Final[dict[str, str]] = {
    "not_uploaded": "gallery_not_uploaded",
    "awaiting_upload": "gallery_processing",
    "processing": "gallery_processing",
    "indexing": "gallery_indexing",
    "failed": "nonrecoverable_error",
    "removed": "nonrecoverable_error",
}
_ENROLLMENT_TERMINAL_STATES: Final[dict[str, str]] = {
    "deleted": "enrollment_deleted",
    "revoked": "access_revoked",
}
_ENROLLMENT_PROGRESS_STATES: Final[dict[str, str]] = {
    "ready": "ready_to_scan",
    "session_pending": "scan_running",
    "processing": "scan_running",
    "rejected": "liveness_rejected",
    "cooldown": "cooldown",
}
_SEARCH_STATES: Final[dict[str, str]] = {
    "queued": "search_queued",
    "searching": "searching",
    "failed": "recoverable_error",
    "cancelled": "recoverable_error",
}


@dataclass(frozen=True, slots=True)
class SummaryStateInputs:
    gallery: MyPhotoGalleryModel | None
    window_state: str
    feature_enabled: bool
    provider_configured: bool
    provider_transient: bool
    gallery_status: str
    enrollment: MyPhotoEnrollmentModel | None
    consent_required: bool
    stale_search: bool
    refresh_failed: bool
    search: MyPhotoSearchRunModel | None
    result_counts: MyPhotosResultsResponse


def experience_state(state: SummaryStateInputs) -> str:
    """Keep capability, consent and then result precedence explicit."""
    return _gallery_state(state) or _enrollment_state(state) or _result_state(state)


def _gallery_state(state: SummaryStateInputs) -> str | None:
    if state.gallery is None or not state.gallery.feature_enabled:
        return "feature_unavailable"
    if state.window_state == "expired":
        return "access_expired"
    if not state.feature_enabled:
        return "feature_unavailable"
    if not state.provider_configured:
        return "provider_not_configured"
    if state.provider_transient:
        return "provider_unavailable"
    return _GALLERY_STATES.get(state.gallery_status)


def _enrollment_state(state: SummaryStateInputs) -> str | None:
    status = state.enrollment.status if state.enrollment is not None else "ready"
    terminal = _ENROLLMENT_TERMINAL_STATES.get(status)
    if terminal is not None:
        return terminal
    if state.consent_required:
        return "consent_required"
    return _ENROLLMENT_PROGRESS_STATES.get(status)


def _result_state(state: SummaryStateInputs) -> str:
    if state.stale_search:
        return "recoverable_error" if state.refresh_failed else "search_queued"
    status = state.search.status if state.search is not None else ""
    running = _SEARCH_STATES.get(status)
    if running is not None:
        return running
    if status == "complete" and state.result_counts.match_count == 0:
        return "no_matches"
    if state.result_counts.preparing_count > 0:
        return "matches_preparing"
    if state.result_counts.match_count > 0:
        return "matches_ready"
    return "ready_to_scan"
