"""Shared Beat runtime for the explicitly paused email/My Photos profile."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from celery.beat import PersistentScheduler


def active_platform_schedule(schedule: Mapping[str, Any]) -> dict[str, Any]:
    """Keep platform entries intact without publishing to paused queues."""
    active = {}
    for name, entry in schedule.items():
        queue = str((entry.get("options") or {}).get("queue", ""))
        task = str(entry.get("task", ""))
        if (
            queue in {"email_integrations", "email_ai"}
            or queue.startswith("my_photos_")
            or task.startswith(("email.", "my_photos."))
        ):
            continue
        active[name] = entry
    return active


class PausedFeatureScheduler(PersistentScheduler):
    def setup_schedule(self) -> None:
        # PersistentScheduler.merge_inplace removes obsolete periodic entries
        # from its own schedule store. Queued jobs in Redis are never touched.
        self.app.conf.beat_schedule = active_platform_schedule(self.app.conf.beat_schedule)
        super().setup_schedule()
