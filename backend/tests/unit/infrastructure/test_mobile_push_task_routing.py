from __future__ import annotations

from app.infrastructure.mobile_push import (
    MOBILE_PUSH_DISPATCH_TASK,
    MOBILE_PUSH_RECEIPT_TASK,
)
from app.infrastructure.processing.celery_app import celery_app, settings


def test_mobile_push_dispatch_and_receipts_share_bounded_worker_schedule() -> None:
    assert celery_app.conf.task_routes[MOBILE_PUSH_DISPATCH_TASK] == {
        "queue": "passport_ocr"
    }
    assert celery_app.conf.task_routes[MOBILE_PUSH_RECEIPT_TASK] == {
        "queue": "passport_ocr"
    }

    dispatch = celery_app.conf.beat_schedule["dispatch-mobile-push-notifications"]
    assert dispatch["task"] == MOBILE_PUSH_DISPATCH_TASK
    assert dispatch["schedule"] == settings.mobile.push_dispatch_interval_seconds
    assert dispatch["options"] == {"queue": "passport_ocr"}

    receipts = celery_app.conf.beat_schedule["reconcile-mobile-push-receipts"]
    assert receipts["task"] == MOBILE_PUSH_RECEIPT_TASK
    assert receipts["schedule"] == settings.mobile.push_receipt_poll_interval_seconds
    assert receipts["options"] == {"queue": "passport_ocr"}
