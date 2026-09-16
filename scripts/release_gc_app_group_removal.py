"""Release GC App trip removal controls, 0098 -> 0099.

Includes backend, frontend and all shared-image workers. Activation requires
paused ingress, drained jobs and a verified preserved database backup. Removal
only changes GC App access; passport groups and their records survive.
Previous images, backups and runner artifacts remain available for diagnosis.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from release_notification_workspace import SCHEMA as PREVIOUS_SCHEMA
from release_reliability import ReliabilityRelease
from release_traveller_whatsapp import ROOT
from release_traveller_whatsapp import main as run_release

SCHEMA = "0099_gc_group_access_removal"


class GCAppGroupRemovalRelease(ReliabilityRelease):
    def __init__(self, revision: str, root: Path = ROOT) -> None:
        super().__init__(
            revision, root, expected_schema=SCHEMA, previous_schema=PREVIOUS_SCHEMA,
            directory_name="gc-app-group-removal-release", include_frontend=True,
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
    return run_release(GCAppGroupRemovalRelease, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
