"""The durable website outbox must have an actual bounded recovery task."""

import asyncio
from types import SimpleNamespace

from app.infrastructure.processing.celery_app import WHATSAPP_SEND_PUBLICATION_TASK, celery_app
from app.infrastructure.whatsapp import tasks, web_publication


def test_beat_routes_registered_publication_to_existing_queue_and_bounded_runtime(monkeypatch):
    calls = []

    async def publish(*, limit, intent_id=None):
        calls.append((limit, intent_id))
        return 2

    monkeypatch.setattr(web_publication, "run_whatsapp_send_publication", publish)
    monkeypatch.setattr(tasks, "celery_async_runtime", SimpleNamespace(run=asyncio.run))
    schedule = celery_app.conf.beat_schedule["publish-whatsapp-send-intents"]
    assert schedule == {"task": WHATSAPP_SEND_PUBLICATION_TASK, "schedule": 60.0,
                        "options": {"queue": "whatsapp", "expires": 60}}
    assert celery_app.conf.task_routes[WHATSAPP_SEND_PUBLICATION_TASK] == {"queue": "whatsapp"}
    registered = celery_app.tasks[WHATSAPP_SEND_PUBLICATION_TASK]
    assert registered() == 2
    assert calls == [(20, None)]
