"""Release the concurrent realtime startup fix on an existing schema 0098 site.

Updates backend and shared-image workers with a fresh verified database backup
for each activation. Retains recovery images, archives and verification runners.
The notification dashboard and existing data volumes remain in place.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from release_notification_workspace import SCHEMA
from release_reliability import ReliabilityRelease
from release_traveller_whatsapp import ROOT
from release_traveller_whatsapp import main as run_release


class RealtimeStartupRelease(ReliabilityRelease):
    def __init__(self, revision: str, root: Path = ROOT) -> None:
        super().__init__(
            revision, root, expected_schema=SCHEMA, previous_schema=SCHEMA,
            directory_name="realtime-startup-release", include_frontend=False,
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
    return run_release(RealtimeStartupRelease, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
