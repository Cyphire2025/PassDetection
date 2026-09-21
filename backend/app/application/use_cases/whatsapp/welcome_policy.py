"""Which message types depend on confirmed delivery of a separate welcome."""

from __future__ import annotations


def requires_prior_welcome(message_type: str) -> bool:
    """Group invitations are independent; unknown/private message types stay gated."""
    return message_type not in {"welcome", "group_invite"}
