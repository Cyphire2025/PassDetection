"""Release Excel import groups and WhatsApp broadcast archives, 0099 -> 0101.

Includes the frontend, backend, all seven workers and beat. Prepare preserves
the previous running images while building the new release. Before activate,
pause external ingress and periodic task production, then drain queued jobs;
--traffic-paused is an operator assertion, not an ingress control mechanism.
Activation requires idle worker snapshots and a verified private database backup.
Previous images, backups and runner artifacts remain available for diagnosis.
Neither migration supports downgrade: retain the schema and recover forward.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from release_gc_app_group_removal import SCHEMA as PREVIOUS_SCHEMA
from release_reliability import ReliabilityRelease
from release_traveller_whatsapp import ROOT
from release_traveller_whatsapp import main as run_release

SCHEMA = "0101_client_group_import_only"


class ImportGroupsArchiveRelease(ReliabilityRelease):
    def __init__(self, revision: str, root: Path = ROOT) -> None:
        super().__init__(
            revision, root, expected_schema=SCHEMA, previous_schema=PREVIOUS_SCHEMA,
            directory_name="import-groups-archive-release", include_frontend=True,
            preserve_release_artifacts=True,
        )

    def preflight(self) -> dict[str, Any]:
        config = super().preflight()
        enabled = config["services"]["worker"].get("environment", {}).get("MOBILE_PUSH_APNS_ENABLED", "false")
        if str(enabled).strip().lower() in {"true", "1"}:
            self.compose.extend(["-f", "docker-compose.apns.yml"])
            config = json.loads(self.dc("config", "--format", "json"))
        return config


def main() -> int:
    return run_release(ImportGroupsArchiveRelease, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
