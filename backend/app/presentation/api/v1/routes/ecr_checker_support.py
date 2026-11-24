"""ECR actor authority, scoped batch reads and response projection."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.security.access_level_actor import (
    actual_user_agency_id,
    actual_user_role,
    refresh_access_level_actor,
)
from app.core.logging.logger import get_logger
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.database.models import AgencyModel, UserModel, UserSecurityStateModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.ecr_read_repository import ECR_ALLOWED_ROLES, ecr_scope
from app.presentation.api.v1.schemas.ecr_schemas import (
    EcrBatchResponse,
    EcrBatchSummary,
    EcrItemResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

logger = get_logger("app.presentation.api.v1.routes.ecr_checker")


UserDep = Annotated[User, Depends(get_current_active_user)]


SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


_MUTATION = [Depends(require_cookie_csrf)]


_ALLOWED_ROLES = ECR_ALLOWED_ROLES


def _scope(user: User) -> list[ColumnElement[bool]]:
    try:
        return ecr_scope(user)
    except AuthorizationError as exc:
        raise HTTPException(403, "Insufficient permissions") from exc


async def _lock_active_actor(session: AsyncSession, user: User) -> User:
    """Revalidate the actor under short shared locks before every mutation.

    Shared locks let upload chunks proceed together while excluding concurrent
    account/agency revocation until the mutation commits. The restricted access
    level of a super administrator is preserved by the common actor helper.
    """

    _scope(user)
    actual_agency_id = actual_user_agency_id(user)
    actor = await session.scalar(
        select(UserModel)
        .join(AgencyModel, AgencyModel.id == user.agency_id)
        .where(
            UserModel.id == user.id,
            UserModel.agency_id == actual_agency_id
            if actual_agency_id is not None
            else UserModel.agency_id.is_(None),
            UserModel.role == actual_user_role(user).value,
            UserModel.is_active.is_(True),
            UserModel.deleted_at.is_(None),
            AgencyModel.is_active.is_(True),
        )
        .with_for_update(read=True, of=[UserModel.id, AgencyModel.id])
        .execution_options(populate_existing=True)
    )
    if actor is None:
        raise HTTPException(403, "Your account or agency is no longer authorized for ECR checking")
    await session.scalar(
        select(UserSecurityStateModel)
        .where(UserSecurityStateModel.user_id == user.id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    return await refresh_access_level_actor(session, user)


async def _batch(
    session: AsyncSession, user: User, batch_id: uuid.UUID, *, lock: bool = False
) -> EcrBatchModel:
    query = select(EcrBatchModel).where(EcrBatchModel.id == batch_id, *_scope(user))
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    batch = (await session.execute(query)).scalar_one_or_none()
    if batch is None:
        raise HTTPException(404, "ECR batch not found")
    return batch


async def _items(session: AsyncSession, batch_id: uuid.UUID) -> list[EcrItemModel]:
    return list(
        (
            await session.execute(
                select(EcrItemModel)
                .where(EcrItemModel.batch_id == batch_id)
                .order_by(EcrItemModel.created_at, EcrItemModel.id)
            )
        ).scalars()
    )


def _summary(batch: EcrBatchModel, items: list[EcrItemModel]) -> EcrBatchSummary:
    return EcrBatchSummary(
        batch_id=batch.id,
        title=batch.title,
        status=batch.status,
        total_count=len(items),
        expected_count=batch.expected_count,
        processed_count=sum(item.status in {"completed", "failed"} for item in items),
        ecr_count=sum(item.result == "ECR" for item in items),
        na_count=sum(item.result == "NA" for item in items),
        review_count=sum(item.result == "NEEDS_REVIEW" for item in items),
        failed_count=sum(item.status == "failed" for item in items),
        created_at=batch.created_at,
    )


async def _response(session: AsyncSession, batch: EcrBatchModel) -> EcrBatchResponse:
    items = await _items(session, batch.id)
    return EcrBatchResponse(
        **_summary(batch, items).model_dump(),
        items=[EcrItemResponse.model_validate(item) for item in items],
    )
