"""Release the notification workspace and saved-message removal, 0097 -> 0098.

Includes backend, frontend and all shared-image workers. Activation requires
paused ingress, drained jobs and a verified preserved database backup. Deletion
only hides saved messages; original send batches and pending delivery survive.
Previous images, backups and runner artifacts remain available for diagnosis.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from release_authored_notifications import SCHEMA as PREVIOUS_SCHEMA
from release_reliability import ReliabilityRelease
from release_traveller_whatsapp import ROOT
from release_traveller_whatsapp import main as run_release

SCHEMA = "0098_notification_saved_delete"


class NotificationWorkspaceRelease(ReliabilityRelease):
    def __init__(self, revision: str, root: Path = ROOT) -> None:
        super().__init__(
            revision, root, expected_schema=SCHEMA, previous_schema=PREVIOUS_SCHEMA,
            directory_name="notification-workspace-release", include_frontend=True,
            preserve_release_artifacts=True,
        )

    def preflight(self) -> dict[str, Any]:
        config = super().preflight()
        enabled = config["services"]["worker"].get("environment", {}).get("MOBILE_PUSH_APNS_ENABLED", "false")
        if str(enabled).lower() in {"true", "1"}:
            self.compose.extend(["-f", "docker-compose.apns.yml"])
            config = json.loads(self.dc("config", "--format", "json"))
        return config


def main() -> int:
    return run_release(NotificationWorkspaceRelease, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
