"""Periodic recovery of durable encrypted directory updates."""

from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.travellers.directory_runtime import run_company_directory_tick


@celery_app.task(name="companies.refresh_directory", queue="passport_ocr", soft_time_limit=30, time_limit=40)  # type: ignore[untyped-decorator]
def refresh_company_directory() -> int:
    return celery_async_runtime.run(run_company_directory_tick())
