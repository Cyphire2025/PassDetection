"""No-provider periodic recovery of committed traveller background work."""

from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.travellers.runtime import (
    run_asset_copy_tick,
    run_reconciliation_tick,
    stage_withdrawn_asset_deletions,
)


@celery_app.task(name="travellers.reconcile", queue="passport_ocr", soft_time_limit=65, time_limit=75)  # type: ignore[untyped-decorator]
def reconcile_traveller_history() -> int:
    return celery_async_runtime.run(run_reconciliation_tick())


@celery_app.task(name="travellers.copy_assets", queue="passport_ocr", soft_time_limit=65, time_limit=75)  # type: ignore[untyped-decorator]
def copy_traveller_assets() -> int:
    return celery_async_runtime.run(run_asset_copy_tick())


@celery_app.task(name="travellers.withdraw_assets", queue="passport_ocr", soft_time_limit=30, time_limit=40)  # type: ignore[untyped-decorator]
def withdraw_traveller_assets() -> int:
    return celery_async_runtime.run(stage_withdrawn_asset_deletions())
