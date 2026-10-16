from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from app.infrastructure.processing.paused_feature_scheduler import (
    PausedFeatureScheduler,
    active_platform_schedule,
)


def test_paused_schedule_filters_only_feature_entries_and_keeps_platform_entries():
    schedule = {
        "email": {"task": "email.dispatch", "options": {"queue": "email_integrations"}},
        "email-ai": {"task": "email.analyze", "options": {"queue": "email_ai"}},
        "photos": {"task": "my_photos.recover", "options": {"queue": "my_photos_control"}},
        "future-email": {"task": "email.future", "options": {"queue": "another_queue"}},
        "lifecycle": {
            "task": "platform.apply_lifecycle_policies",
            "options": {"queue": "passport_ocr"},
        },
        "heartbeat": {"task": "platform.scheduler_heartbeat", "options": {"queue": "passport_ocr"}},
        "documents": {"task": "documents.cleanup_storage", "options": {"queue": "passport_ocr"}},
        "mobile": {"task": "mobile.dispatch", "options": {"queue": "passport_ocr"}},
        "whatsapp": {"task": "whatsapp.recover", "options": {"queue": "whatsapp"}},
    }
    before = deepcopy(schedule)
    result = active_platform_schedule(schedule)
    assert set(result) == {"lifecycle", "heartbeat", "documents", "mobile", "whatsapp"}
    assert schedule == before
    assert all(result[key] is schedule[key] for key in result)


def test_persistent_schedule_is_filtered_before_existing_store_is_merged():
    app = SimpleNamespace(
        conf=SimpleNamespace(
            beat_schedule={
                "email": {"task": "email.dispatch"},
                "heartbeat": {"task": "platform.scheduler_heartbeat"},
            }
        )
    )
    scheduler = object.__new__(PausedFeatureScheduler)
    scheduler.app = app

    def setup():
        assert set(app.conf.beat_schedule) == {"heartbeat"}

    with patch("celery.beat.PersistentScheduler.setup_schedule", side_effect=setup) as parent:
        scheduler.setup_schedule()
    parent.assert_called_once()
