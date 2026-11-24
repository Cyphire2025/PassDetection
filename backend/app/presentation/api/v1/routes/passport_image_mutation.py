"""Current image authority with the existing caller's source-conflict message."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.snapshot_access import can_read_snapshot_asset
from app.domain.entities.entities import PassportSubmission, User
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.presentation.api.v1.routes.passport_image_library_authority import (
    lock_passport_image_mutation as _lock_actor_and_scope,
)


async def lock_passport_image_mutation(
    session: AsyncSession,
    *,
    current_user: User,
    submission: PassportSubmission,
    image_type: PassportImageType,
    source_key: str,
) -> tuple[User, PassportSubmission]:
    """Recheck retained evidence as well as the locked actor and trip scope."""
    actor, locked = await _lock_actor_and_scope(
        session,
        current_user=current_user,
        submission=submission,
        image_type=image_type,
        source_key=source_key,
    )
    if source_key.startswith("travellers/") and not await can_read_snapshot_asset(
        session,
        submission_id=locked.id,
        group_id=locked.group_id,
        agency_id=locked.agency_id,
        storage_key=source_key,
    ):
        raise HTTPException(status_code=404, detail="The requested image is unavailable.")
    return actor, locked


async def lock_current_image_editor(
    session: AsyncSession,
    *,
    current_user: User,
    submission: PassportSubmission,
    image_type: PassportImageType,
    source_key: str,
    changed_detail: str,
) -> tuple[User, PassportSubmission]:
    """Keep source conflicts compatible while sharing the locked policy boundary."""
    try:
        return await lock_passport_image_mutation(
            session,
            current_user=current_user,
            submission=submission,
            image_type=image_type,
            source_key=source_key,
        )
    except HTTPException as exc:
        if exc.status_code == 409:
            raise HTTPException(status_code=409, detail=changed_detail) from exc
        raise
