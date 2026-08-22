from __future__ import annotations

from app.infrastructure.processing.celery_app import (
    DEFAULT_TASK_SOFT_TIME_LIMIT_SECONDS,
    DEFAULT_TASK_TIME_LIMIT_SECONDS,
    DOCUMENT_STORAGE_CLEANUP_TASK,
    EMAIL_SYNC_TASK,
    MOBILE_PUSH_DISPATCH_TASK,
    PLATFORM_LIFECYCLE_TASK,
    VISA_AI_IMAGE_TASK,
    WHATSAPP_BROADCAST_TASK,
    WHATSAPP_DOCUMENT_BROADCAST_TASK,
    WHATSAPP_QR_BROADCAST_TASK,
    WORKER_MAX_MEMORY_PER_CHILD_KIB,
    WORKER_MAX_TASKS_PER_CHILD,
    celery_app,
)


def test_every_celery_worker_has_a_finite_resource_envelope() -> None:
    assert celery_app.conf.task_soft_time_limit == DEFAULT_TASK_SOFT_TIME_LIMIT_SECONDS
    assert celery_app.conf.task_time_limit == DEFAULT_TASK_TIME_LIMIT_SECONDS
    assert 0 < celery_app.conf.task_soft_time_limit < celery_app.conf.task_time_limit
    assert celery_app.conf.worker_max_tasks_per_child == WORKER_MAX_TASKS_PER_CHILD
    assert celery_app.conf.worker_max_memory_per_child == WORKER_MAX_MEMORY_PER_CHILD_KIB
    assert celery_app.conf.worker_cancel_long_running_tasks_on_connection_loss is True
    assert celery_app.conf.task_track_started is True


def test_high_risk_tasks_have_tighter_soft_and_hard_limits() -> None:
    annotations = celery_app.conf.task_annotations
    for task_name in (
        "passport.process_submission",
        "passport.verify_submitted",
        VISA_AI_IMAGE_TASK,
        EMAIL_SYNC_TASK,
        "email.analyze_travel_message",
        WHATSAPP_BROADCAST_TASK,
        WHATSAPP_DOCUMENT_BROADCAST_TASK,
        WHATSAPP_QR_BROADCAST_TASK,
        DOCUMENT_STORAGE_CLEANUP_TASK,
        PLATFORM_LIFECYCLE_TASK,
        MOBILE_PUSH_DISPATCH_TASK,
    ):
        envelope = annotations[task_name]
        assert 0 < envelope["soft_time_limit"] < envelope["time_limit"]
        assert envelope["time_limit"] <= DEFAULT_TASK_TIME_LIMIT_SECONDS


def test_platform_lifecycle_policy_enforcement_is_routed_and_scheduled() -> None:
    assert celery_app.conf.task_routes[PLATFORM_LIFECYCLE_TASK] == {
        "queue": "passport_ocr"
    }
    schedule = celery_app.conf.beat_schedule["apply-platform-lifecycle-policies"]
    assert schedule["task"] == PLATFORM_LIFECYCLE_TASK
    assert schedule["schedule"] == 86_400.0
    assert schedule["options"]["queue"] == "passport_ocr"
