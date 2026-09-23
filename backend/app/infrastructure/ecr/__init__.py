"""Durable, isolated processing for the Documents ECR checker."""

ECR_QUEUE = "ecr_checks"
ECR_BATCH_TASK = "ecr.process_batch"
ECR_RECOVERY_TASK = "ecr.recover_batches"
ECR_RETENTION_TASK = "ecr.apply_retention"


async def dispatch_ecr_batch(batch_id: object) -> None:
    """Publish after the caller commits its durable queued batch.

    Broker failures deliberately propagate to the caller; the scheduled recovery
    task will also find the committed queued row after service recovery.
    """
    import asyncio

    from app.infrastructure.processing.celery_app import celery_app

    await asyncio.to_thread(
        celery_app.send_task,
        ECR_BATCH_TASK,
        args=[str(batch_id)],
        queue=ECR_QUEUE,
        retry=False,
    )
