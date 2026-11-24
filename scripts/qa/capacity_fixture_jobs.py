"""Publish the fixed missing-image burst and verify its durable terminal records."""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta

from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.database.models import (
    AttendanceRecordModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.ecr import ECR_RECOVERY_TASK
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from capacity_fixture_contract import TENANTS, identifier
from PIL import Image
from sqlalchemy import func, select


async def queue_retries(run_id: str) -> dict:
    """Real durable failures/recovery with absent images; never invoke external AI."""
    observed = datetime.now(UTC)
    batches = []
    async with AsyncSessionFactory() as db:
        for index in range(100):
            batch_id = uuid.uuid4()
            batches.append(batch_id)
            db.add(
                EcrBatchModel(
                    id=batch_id,
                    agency_id=identifier(run_id, f"agency-{index % TENANTS}"),
                    title=f"capacity-{run_id}",
                    expected_count=1,
                    status="queued",
                    created_at=observed,
                    updated_at=observed - timedelta(minutes=30),
                )
            )
            await db.flush()
            db.add(
                EcrItemModel(
                    id=uuid.uuid4(),
                    batch_id=batch_id,
                    client_id=uuid.uuid4(),
                    original_filename="synthetic-missing.jpg",
                    object_key=None,
                    content_type="image/jpeg",
                    sha256="0" * 64,
                    status="queued",
                    created_at=observed,
                    updated_at=observed,
                )
            )
        await db.commit()
    # Duplicate delivery is deliberate: durable item claims must prevent more
    # than one terminal attempt. Recovery also competes in the general queue.
    task_ids = [
        celery_app.send_task("ecr.process_batch", args=[str(batch)], queue="ecr_checks").id
        for batch in batches
        for _ in range(3)
    ]
    task_ids += [
        celery_app.send_task(ECR_RECOVERY_TASK, queue="passport_ocr").id for _ in range(10)
    ]
    return {
        "durable_jobs": len(batches),
        "deliveries": len(task_ids),
        "external_ai_invoked": False,
    }


async def verify(run_id: str) -> dict:
    async with AsyncSessionFactory() as db:
        rows = (
            await db.execute(
                select(
                    EcrBatchModel.status,
                    EcrItemModel.status,
                    EcrItemModel.reason,
                    EcrItemModel.attempts,
                )
                .join(EcrItemModel, EcrItemModel.batch_id == EcrBatchModel.id)
                .where(EcrBatchModel.title == f"capacity-{run_id}")
            )
        ).all()
        if len(rows) != 100 or any(
            tuple(row) != ("completed_with_errors", "failed", "image_expired", 1) for row in rows
        ):
            raise RuntimeError(
                "Retry burst has not settled to exactly one expected durable terminal attempt per item"
            )
        sessions = [identifier(run_id, f"attendance-{index}") for index in range(TENANTS)]
        scans = await db.scalar(
            select(func.count())
            .select_from(AttendanceRecordModel)
            .where(AttendanceRecordModel.session_id.in_(sessions))
        )
        uploads = (
            await db.execute(
                select(
                    PassportSubmissionModel.passport_cover_s3_key,
                    PassportSubmissionModel.passport_back_cover_s3_key,
                ).where(
                    PassportSubmissionModel.group_id.in_(
                        [identifier(run_id, f"public-{index}") for index in range(4)]
                    )
                )
            )
        ).all()
    stored_hashes = set()
    storage = MinioStorageRepository()
    for upload in uploads:
        for key in upload:
            if not key:
                raise RuntimeError("A persisted synthetic upload is missing a cover")
            content = await storage.get_file(key)
            with Image.open(io.BytesIO(content)) as cover:
                if cover.size != (1200, 800) or cover.format != "JPEG":
                    raise RuntimeError("Stored synthetic cover does not match its image contract")
                cover.verify()
            stored_hashes.add(hashlib.sha256(content).hexdigest())
    return {
        "durable_jobs_verified": len(rows),
        "attempts_per_item": 1,
        "expected_failure_reason": "image_expired",
        "persisted_unique_scans": scans,
        "persisted_uploads": len(uploads),
        "distinct_readable_upload_objects": len(stored_hashes),
    }


# Preserve the original function identity through capacity_fixtures.
for _export in (
    queue_retries,
    verify,
):
    _export.__module__ = "capacity_fixtures"
del _export
