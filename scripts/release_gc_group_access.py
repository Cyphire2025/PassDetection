"""Release GC App workflow and submitted-phone authorization, 0095 -> 0096.

Prepare backend, frontend and their shared worker release at one exact revision.
Activation requires paused traffic, idle workers and a fresh validated database
backup. The only migration adds a phone lookup index; no contact is rewritten
and provider configuration stays unchanged. A retry on 0096 requires this
commit's preserved pre-migration 0095 backup.
Recovery images, private backups, temporary files and one-off containers remain
available after activation.
"""

from __future__ import annotations

from pathlib import Path

from release_mobile_fcm import SCHEMA as PREVIOUS_SCHEMA
from release_reliability import ReliabilityRelease
from release_traveller_whatsapp import ROOT
from release_traveller_whatsapp import main as run_release

SCHEMA = "0096_mobile_phone_lookup"


class GCGroupAccessRelease(ReliabilityRelease):
    def __init__(self, revision: str, root: Path = ROOT) -> None:
        super().__init__(
            revision, root, expected_schema=SCHEMA, previous_schema=PREVIOUS_SCHEMA,
            directory_name="gc-group-access-release", include_frontend=True,
            preserve_release_artifacts=True,
        )


def main() -> int:
    return run_release(GCGroupAccessRelease, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
