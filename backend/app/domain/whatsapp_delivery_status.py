"""Shared delivery evidence vocabulary; provider acceptance is not delivery."""

from __future__ import annotations

from datetime import timedelta

WHATSAPP_ACCEPTED_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})
WHATSAPP_ACCEPTED_STATUS_RANK = {"submitted": 0, "sent": 1, "delivered": 2, "read": 3}
WHATSAPP_WEBHOOK_STATUSES = frozenset({"sent", "delivered", "read", "failed"})
WHATSAPP_IN_PROGRESS_STATUSES = frozenset({"queued", "processing"})
WHATSAPP_UNCERTAIN_STATUSES = frozenset({"delivery_unknown"})
WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES = (
    WHATSAPP_IN_PROGRESS_STATUSES | WHATSAPP_UNCERTAIN_STATUSES
)
WHATSAPP_SUPPRESSED_STATUSES = (
    WHATSAPP_ACCEPTED_STATUSES | WHATSAPP_IN_PROGRESS_STATUSES | WHATSAPP_UNCERTAIN_STATUSES
)
WHATSAPP_STALE_CLAIM_AGE = timedelta(minutes=30)

# Keep all recorded states separate in diagnostic/read projections. A new or
# unsupported state is unknown evidence, never an inferred delivery success.
WHATSAPP_READ_STATUS_KEYS = (
    "queued", "processing", "submitted", "sent", "delivered", "read", "failed",
    "delivery_unknown", "stalled", "cancelled", "dry_run", "unrecognized",
)
