"""Periodic recovery discovers committed drafts without best-effort dispatch."""
from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.travellers.draft_runtime import expire_draft_assets, run_draft_extraction


async def _tick() -> int:
    cleaned = await expire_draft_assets()
    return cleaned + await run_draft_extraction()


@celery_app.task(name="travellers.returning_drafts", queue="passport_ocr", soft_time_limit=50, time_limit=60)  # type: ignore[untyped-decorator]
def returning_drafts() -> int:
    return celery_async_runtime.run(_tick())
