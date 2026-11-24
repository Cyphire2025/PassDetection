"""ECR start, retry and completed-workbook actions with durable dispatch."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.infrastructure.export.ecr_excel_exporter import build_ecr_workbook
from app.presentation.api.v1.response_contracts import XLSX, binary_responses
from app.presentation.api.v1.routes.ecr_checker_support import (
    _MUTATION,
    SessionDep,
    UserDep,
    _batch,
    _items,
    _lock_active_actor,
    _response,
    logger,
)
from app.presentation.api.v1.schemas.ecr_schemas import EcrBatchResponse

router = APIRouter()


async def _dispatch(batch_id: uuid.UUID) -> None:
    from app.infrastructure.ecr import dispatch_ecr_batch

    try:
        await dispatch_ecr_batch(batch_id)
    except Exception:
        # The committed queued row is the outbox; scheduled recovery republishes it.
        logger.warning("ecr_dispatch_deferred", batch_id=str(batch_id))


@router.post("/batches/{batch_id}/start", response_model=EcrBatchResponse, dependencies=_MUTATION)
async def start_ecr_batch(
    batch_id: uuid.UUID, current_user: UserDep, session: SessionDep
) -> EcrBatchResponse:
    current_user = await _lock_active_actor(session, current_user)
    batch = await _batch(session, current_user, batch_id, lock=True)
    if batch.status != "uploading":
        return await _response(session, batch)
    items = await _items(session, batch_id)
    if len(items) != batch.expected_count:
        raise HTTPException(409, "Finish uploading every selected file before starting")
    batch.status = "queued"
    await session.commit()
    await _dispatch(batch.id)
    return await _response(session, batch)


@router.post("/batches/{batch_id}/retry", response_model=EcrBatchResponse, dependencies=_MUTATION)
async def retry_ecr_batch(
    batch_id: uuid.UUID, current_user: UserDep, session: SessionDep
) -> EcrBatchResponse:
    current_user = await _lock_active_actor(session, current_user)
    batch = await _batch(session, current_user, batch_id, lock=True)
    if batch.status not in {"completed", "completed_with_errors"}:
        raise HTTPException(409, "Wait until this batch finishes before retrying failed checks")
    retry = [
        item
        for item in await _items(session, batch_id)
        if item.status == "failed" and item.object_key
    ]
    if not retry:
        raise HTTPException(
            409, "No retryable images remain. Upload invalid or expired images in a new batch"
        )
    for item in retry:
        item.status, item.result, item.reason = "queued", None, None
    batch.status, batch.lease_token, batch.lease_expires_at = "queued", None, None
    await session.commit()
    await _dispatch(batch.id)
    return await _response(session, batch)


@router.get("/batches/{batch_id}/export.xlsx", response_class=Response, responses=binary_responses(XLSX))
async def export_ecr_batch(
    batch_id: uuid.UUID, current_user: UserDep, session: SessionDep
) -> Response:
    batch = await _batch(session, current_user, batch_id)
    items = await _items(session, batch.id)
    if (
        batch.status not in {"completed", "completed_with_errors"}
        or len(items) != batch.expected_count
    ):
        raise HTTPException(
            409, "Wait until every file has finished before downloading the Excel sheet"
        )
    rows = [
        (
            item.original_filename,
            "ERROR"
            if item.status == "failed"
            else "REVIEW"
            if item.result == "NEEDS_REVIEW"
            else item.result or "PENDING",
        )
        for item in items
    ]
    content = await asyncio.to_thread(build_ecr_workbook, rows)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="ECR-{batch.id}.xlsx"',
            "Cache-Control": "no-store",
        },
    )
