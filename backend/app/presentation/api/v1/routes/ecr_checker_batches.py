"""Create and read standalone ECR batches in their current agency scope."""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app.infrastructure.database.ecr_models import EcrBatchModel
from app.infrastructure.repositories.ecr_read_repository import ECR_COUNT_FIELDS, ecr_item_counts
from app.presentation.api.v1.routes.ecr_checker_support import (
    _MUTATION,
    SessionDep,
    UserDep,
    _batch,
    _lock_active_actor,
    _response,
    _scope,
)
from app.presentation.api.v1.schemas.ecr_schemas import (
    CreateEcrBatch,
    EcrBatchResponse,
    EcrBatchSummary,
)

router = APIRouter()


@router.post("/batches", response_model=EcrBatchResponse, dependencies=_MUTATION, status_code=201)
async def create_ecr_batch(
    body: CreateEcrBatch, current_user: UserDep, session: SessionDep
) -> EcrBatchResponse:
    current_user = await _lock_active_actor(session, current_user)
    batch = EcrBatchModel(
        agency_id=current_user.agency_id,
        created_by_user_id=current_user.id,
        title=body.title.strip() or "ECR check",
        expected_count=body.expected_count,
    )
    session.add(batch)
    await session.commit()
    return await _response(session, batch)


@router.get("/batches", response_model=list[EcrBatchSummary])
async def list_ecr_batches(current_user: UserDep, session: SessionDep) -> list[EcrBatchSummary]:
    batches = list(
        (
            await session.execute(
                select(EcrBatchModel)
                .where(*_scope(current_user))
                .order_by(EcrBatchModel.created_at.desc())
                .limit(50)
            )
        ).scalars()
    )
    if not batches:
        return []
    counts = await ecr_item_counts(session, [batch.id for batch in batches])
    return [
        EcrBatchSummary(
            batch_id=batch.id,
            title=batch.title,
            status=batch.status,
            expected_count=batch.expected_count,
            created_at=batch.created_at,
            **{
                name: int(counts.get(batch.id, {}).get(name, 0))
                for name in ECR_COUNT_FIELDS
            },
        )
        for batch in batches
    ]


@router.get("/batches/{batch_id}", response_model=EcrBatchResponse)
async def get_ecr_batch(
    batch_id: uuid.UUID, current_user: UserDep, session: SessionDep
) -> EcrBatchResponse:
    return await _response(session, await _batch(session, current_user, batch_id))
