"""Canonical My Photos state machines shared by services and adapters."""

from __future__ import annotations

from typing import Literal

GalleryStatus = Literal[
    "not_uploaded",
    "awaiting_upload",
    "processing",
    "indexing",
    "ready",
    "failed",
    "removed",
]
EnrollmentStatus = Literal[
    "consent_required",
    "ready",
    "session_pending",
    "processing",
    "enrolled",
    "rejected",
    "cooldown",
    "revoked",
    "deleted",
]
LivenessSessionStatus = Literal[
    "creating",
    "created",
    "running",
    "completed",
    "cancelled",
    "expired",
    "rejected",
    "failed",
]
SearchStatus = Literal[
    "not_started",
    "queued",
    "searching",
    "complete",
    "failed",
    "cancelled",
]
MatchTier = Literal["best", "possible"]
MatchFilter = Literal["best", "possible", "all"]
MatchFeedback = Literal["none", "this_is_me", "not_me"]
ChallengeMode = Literal["movement_and_light", "movement_only"]
MediaAvailability = Literal[
    "registered",
    "awaiting_upload",
    "processing",
    "indexed",
    "preview_available",
    "original_available_online",
    "archived_offline",
    "rehydration_requested",
    "preparing_delivery",
    "delivery_available",
    "expired",
    "failed",
    "removed",
]
JobStatus = Literal[
    "queued",
    "running",
    "retrying",
    "succeeded",
    "cancelled",
    "failed",
]
DeliveryStatus = Literal[
    "preparing",
    "available",
    "expired",
    "failed",
    "cancelled",
]
ExperienceState = Literal[
    "feature_unavailable",
    "provider_not_configured",
    "gallery_not_uploaded",
    "gallery_processing",
    "gallery_indexing",
    "consent_required",
    "camera_permission_required",
    "ready_to_scan",
    "scan_running",
    "scan_cancelled",
    "session_expired",
    "liveness_rejected",
    "cooldown",
    "device_unsupported",
    "provider_unavailable",
    "search_queued",
    "searching",
    "no_matches",
    "matches_preparing",
    "matches_ready",
    "offline_results",
    "partial_offline_results",
    "access_expired",
    "access_revoked",
    "recoverable_error",
    "nonrecoverable_error",
    "enrollment_deleted",
]

GALLERY_STATUSES = frozenset(
    {"not_uploaded", "awaiting_upload", "processing", "indexing", "ready", "failed", "removed"}
)
ENROLLMENT_STATUSES = frozenset(
    {
        "consent_required",
        "ready",
        "session_pending",
        "processing",
        "enrolled",
        "rejected",
        "cooldown",
        "revoked",
        "deleted",
    }
)
MEDIA_AVAILABILITY_STATES = frozenset(
    {
        "registered",
        "awaiting_upload",
        "processing",
        "indexed",
        "preview_available",
        "original_available_online",
        "archived_offline",
        "rehydration_requested",
        "preparing_delivery",
        "delivery_available",
        "expired",
        "failed",
        "removed",
    }
)

# Exhaustive passenger-delivery policy. Recognition metadata can outlive online
# media, but only these states may produce bytes. Nonterminal states remain
# visible as preparation/in-progress; failed is an explicit item failure and
# removed is omitted from passenger pages entirely.
MEDIA_DELIVERY_READY_STATES = frozenset({"original_available_online", "delivery_available"})
MEDIA_TERMINAL_STATES = frozenset({"failed", "removed"})
MEDIA_PREPARING_STATES = MEDIA_AVAILABILITY_STATES - (
    MEDIA_DELIVERY_READY_STATES | MEDIA_TERMINAL_STATES
)
MEDIA_REHYDRATABLE_STATES = frozenset({"preview_available", "archived_offline", "expired"})
