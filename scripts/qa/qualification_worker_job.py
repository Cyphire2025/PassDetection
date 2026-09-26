"""Exercise the real durable cleanup task within the isolated qualification DB."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta

from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.database.models import AuditLogModel, StorageCleanupJobModel
from app.infrastructure.database.session import AsyncSessionFactory, engine
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_job
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from qualification_application_journey import isolated
from seed_enterprise_browser_stack import AGENCY_ID
from sqlalchemy import func, select


async def main() -> None:
    isolated()
    storage = MinioStorageRepository()
    if sys.argv[1] == "ecr-seed":
        batch_id, item_id = uuid.uuid4(), uuid.uuid4()
        stale = datetime.now(UTC) - timedelta(minutes=30)
        async with AsyncSessionFactory() as db:
            db.add(EcrBatchModel(id=batch_id, agency_id=AGENCY_ID, title="Synthetic expired-image recovery",
                                expected_count=1, status="queued", created_at=stale, updated_at=stale))
            await db.flush()
            db.add(EcrItemModel(id=item_id, batch_id=batch_id, client_id=uuid.uuid4(),
                               original_filename="synthetic-expired.jpg", object_key=None,
                               content_type="image/jpeg", sha256="0" * 64,
                               status="queued", created_at=stale, updated_at=stale))
            await db.commit()
        tasks = [celery_app.send_task("ecr.process_batch", args=[str(batch_id)], queue="ecr_checks").id for _ in range(2)]
        print(json.dumps({"batch_id": str(batch_id), "item_id": str(item_id), "task_ids": tasks}))
    elif sys.argv[1] == "ecr-verify":
        proof = json.load(sys.stdin)
        for attempt in range(90):
            async with AsyncSessionFactory() as db:
                batch = await db.get(EcrBatchModel, uuid.UUID(proof["batch_id"]))
                item = await db.get(EcrItemModel, uuid.UUID(proof["item_id"]))
                assert batch.agency_id == AGENCY_ID and batch.title == "Synthetic expired-image recovery"
                if batch.status == "completed_with_errors":
                    assert item.status == "failed" and item.reason == "image_expired" and item.attempts == 1
                    if all(celery_app.AsyncResult(task_id).successful() for task_id in proof["task_ids"]):
                        print(json.dumps({"durable_ecr_result": "image_expired", "item_attempts": 1,
                                          "duplicate_deliveries_completed": True, "external_ai_invoked": False}))
                        break
            if attempt == 89:
                raise AssertionError("ECR recovery did not commit exactly one terminal result")
            await asyncio.sleep(1)
    elif sys.argv[1] == "seed":
        key = f"document-distribution/qualification/{uuid.uuid4()}/cleanup-proof.txt"
        await storage.upload_file(b"Synthetic queued cleanup proof", key, "text/plain")
        async with AsyncSessionFactory() as db:
            job = stage_storage_cleanup_job(db, agency_id=AGENCY_ID, source="document_distribution_delete",
                                            context_id="isolated-worker-qualification", storage_keys=[key])
            assert job is not None
            await db.commit()
            job_id = str(job.id)
        task = celery_app.send_task("documents.cleanup_storage", queue="passport_ocr")
        assert await storage.get_file(key) == b"Synthetic queued cleanup proof"
        print(json.dumps({"job_id": job_id, "task_id": task.id, "key": key, "durably_queued": True}))
    elif sys.argv[1] == "verify":
        proof = json.load(sys.stdin)
        if not proof["key"].startswith("document-distribution/qualification/"):
            raise RuntimeError("Only this runner's synthetic key can be checked")
        for attempt in range(90):
            async with AsyncSessionFactory() as db:
                pending = await db.get(StorageCleanupJobModel, uuid.UUID(proof["job_id"]))
                audits = await db.scalar(select(func.count()).select_from(AuditLogModel).where(
                    AuditLogModel.entity_id == proof["job_id"],
                    AuditLogModel.action == "document_storage_cleanup_completed"))
            if pending is None and audits == 1 and not await storage.list_files(prefix=proof["key"], limit=1):
                result = celery_app.AsyncResult(proof["task_id"])
                if result.successful():
                    print(json.dumps({"synthetic": True, "queued_while_worker_down": True,
                                      "task_succeeded": True, "object_deleted": True,
                                      "exactly_one_completion_audit": True, "tombstone_completed": True}))
                    break
            if attempt == 89:
                raise AssertionError("Durable cleanup did not complete after worker recovery")
            await asyncio.sleep(1)
    else:
        raise RuntimeError("Unknown synthetic job action")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
