"""Periodic recovery is bounded and performs no external messaging."""

from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.travellers.impact_runtime import run_impact_tick


@celery_app.task(name="travellers.document_impact", queue="passport_ocr", soft_time_limit=65, time_limit=75)  # type: ignore[untyped-decorator]
def process_document_impact() -> int:
    return celery_async_runtime.run(run_impact_tick())
