"""Revalidate the image editor and target scope after external processing."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.access_level_actor import (
    actual_user_agency_id,
    actual_user_role,
    refresh_access_level_actor,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import PassportSubmission, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
    passport_image_storage_key,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ManagerGroupAccessModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read


async def lock_passport_image_mutation(
    session: AsyncSession,
    *,
    current_user: User,
    submission: PassportSubmission,
    image_type: PassportImageType,
    source_key: str,
) -> tuple[User, PassportSubmission]:
    """Use the existing confirmation policy under actor/group/target row locks."""
    actor_agency_id = actual_user_agency_id(current_user)
    actor_model = (
        await session.execute(
            select(UserModel)
            .where(
                UserModel.id == current_user.id,
                UserModel.role == actual_user_role(current_user).value,
                UserModel.agency_id == actor_agency_id
                if actor_agency_id is not None
                else UserModel.agency_id.is_(None),
                UserModel.is_active.is_(True),
                UserModel.deleted_at.is_(None),
            )
            .with_for_update(of=UserModel)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if actor_model is None:
        raise HTTPException(
            status_code=403, detail="Your account permissions changed. Sign in again and retry."
        )
    # Serialize session/credential revocation too. The locked parent user also
    # fences insertion of security state for a legacy account with no row yet.
    (
        await session.execute(
            select(UserSecurityStateModel)
            .where(
                UserSecurityStateModel.user_id == current_user.id,
            )
            .with_for_update(of=UserSecurityStateModel)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    try:
        actor = await refresh_access_level_actor(session, current_user)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    if actor_agency_id is not None:
        agency = (
            await session.execute(
                select(AgencyModel)
                .where(
                    AgencyModel.id == actor_agency_id,
                    AgencyModel.is_active.is_(True),
                )
                .with_for_update(of=AgencyModel)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if agency is None:
            raise HTTPException(status_code=403, detail="Your agency is no longer active.")
    group = (
        await session.execute(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == submission.group_id,
                ClientGroupModel.agency_id == submission.agency_id,
            )
            .with_for_update(of=ClientGroupModel)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=403, detail="This passport group is no longer available.")
    if actor.role is UserRole.AGENCY_STAFF and group.created_by_user_id != actor.id:
        await session.execute(
            select(ManagerGroupAccessModel)
            .where(
                ManagerGroupAccessModel.manager_id == actor.id,
                ManagerGroupAccessModel.group_id == group.id,
            )
            .with_for_update(of=ManagerGroupAccessModel)
            .execution_options(populate_existing=True)
        )
    locked = await PassportSubmissionRepository(session).get_by_id_for_update(submission.id)
    if (
        locked is None
        or locked.agency_id != submission.agency_id
        or locked.group_id != submission.group_id
        or passport_image_storage_key(locked, image_type) != source_key
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The passport image or group changed. Refresh it and try again.",
        )
    try:
        await AuthorizationPolicy(session).require_confirm_passport(actor, locked)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    await record_sensitive_read(
        session,
        user=actor,
        kind="image",
        agency_id=locked.agency_id,
        entity_id=locked.id,
    )
    return actor, locked
