"""Release separate phone notifications and APNs support, 0096 -> 0097.

Includes backend, frontend and all shared-image workers. Activation requires
paused ingress, drained jobs and a verified preserved database backup. The
additive migration preserves announcement content/history and separates native
phone delivery from publication. Apple delivery stays disabled until configured.
Never downgrade: an old worker could resume obsolete announcement phone sends.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from release_gc_group_access import SCHEMA as PREVIOUS_SCHEMA
from release_reliability import ReliabilityRelease
from release_traveller_whatsapp import ROOT
from release_traveller_whatsapp import main as run_release

SCHEMA = "0097_authored_notifications"


class AuthoredNotificationRelease(ReliabilityRelease):
    def __init__(self, revision: str, root: Path = ROOT) -> None:
        super().__init__(
            revision, root, expected_schema=SCHEMA, previous_schema=PREVIOUS_SCHEMA,
            directory_name="authored-notification-release", include_frontend=True,
            preserve_release_artifacts=True,
        )

    def preflight(self) -> dict[str, Any]:
        config = super().preflight()
        enabled = config["services"]["worker"].get("environment", {}).get("MOBILE_PUSH_APNS_ENABLED", "false")
        if str(enabled).lower() in {"true", "1"}:
            # Keep the optional secret mount in both prepare and activation.
            # Missing host directories fail closed because create_host_path is false.
            self.compose.extend(["-f", "docker-compose.apns.yml"])
            config = json.loads(self.dc("config", "--format", "json"))
        return config


def main() -> int:
    return run_release(AuthoredNotificationRelease, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
