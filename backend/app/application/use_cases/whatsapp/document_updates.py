"""Audience rules for pending document updates, independent of delivery retries."""

from __future__ import annotations

import uuid

ACCEPTED = frozenset({"submitted", "sent", "delivered", "read"})
ACTIVE = frozenset({"queued", "processing", "delivery_unknown"})


def needs_document_update(document_ids: set[uuid.UUID], confirmed_ids: set[uuid.UUID]) -> bool:
    """Missing, partially sent, failed and unknown documents remain in the audience."""
    return not document_ids or not document_ids.issubset(confirmed_ids)


def render_document_update(content: str) -> str:
    return (
        "Dear Delegates\n\nGreetings from Global Connect Travels.\n\n"
        f"{content.strip()}\n\nRegards,\nTeam Global Connect Travels"
    )
