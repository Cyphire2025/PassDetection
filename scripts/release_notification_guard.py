"""Prepare and activate the notification guard on an existing schema 0094 site.

This backend/worker-only release accepts only 0094_whatsapp_receipt_inbox. Every activation
attempt captures and validates a fresh private database backup. Previous images,
exact revision, paused traffic, idle workers, and service health remain governed
by the shared release helper. Frontend is not built or restarted, and no provider
setting is enabled by this command. Temporary backups, failed partial writes and
one-off check containers are retained; application containers are replaced as
required to activate the prepared images, preserving data and recovery images.
"""

from __future__ import annotations

from pathlib import Path

from release_reliability import SCHEMA, ReliabilityRelease
from release_traveller_whatsapp import ROOT
from release_traveller_whatsapp import main as run_release


class NotificationGuardRelease(ReliabilityRelease):
    def __init__(self, revision: str, root: Path = ROOT) -> None:
        super().__init__(
            revision, root, previous_schema=SCHEMA,
            directory_name="notification-guard-release",
            include_frontend=False,
            preserve_release_artifacts=True,
        )


def main() -> int:
    return run_release(NotificationGuardRelease, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
