"""Dedicated durable export consumer; no messages or provider calls."""

from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.travellers.company_export_cleanup import expire_export_parts
from app.infrastructure.travellers.company_export_worker import run_company_export_tick


@celery_app.task(name="travellers.company_data_export", queue="passport_ocr", soft_time_limit=190, time_limit=210)  # type: ignore[untyped-decorator]
def company_data_export_tick() -> int:
    async def tick() -> int:
        await expire_export_parts()
        return await run_company_export_tick()
    return celery_async_runtime.run(tick())
