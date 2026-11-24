"""Optional request intent may reject a credential owner, never establish one."""

from __future__ import annotations

import uuid

from app.domain.exceptions.exceptions import ConflictError


def require_expected_actor(actual_user_id: uuid.UUID, expected_actor_id: str | None) -> None:
    if expected_actor_id is not None and expected_actor_id != str(actual_user_id):
        raise ConflictError(
            "The signed-in account changed. Retry from the original account.",
            code="AUTH_REQUEST_OWNER_CHANGED",
        )
