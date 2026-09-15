"""Prepare and activate the direct FCM release, schema 0094 -> 0095.

Build and activate backend, frontend, seven workers and Beat using exact prepared
image IDs. Activation requires paused traffic, idle workers and a verified private
pre-migration database backup. A retry on 0095 must retain the same commit's 0094
backup evidence; this is not a general same-schema release helper. Previous image
tags, temporary archives, failed partial files and one-off containers are retained.
Application containers are replaced to activate new images; database contents,
uploaded files and named volumes are preserved. Provider settings and credentials
are never inferred or changed by this helper.
"""

from __future__ import annotations

from pathlib import Path

from release_reliability import ReliabilityRelease
from release_traveller_whatsapp import ROOT
from release_traveller_whatsapp import main as run_release

SCHEMA = "0095_mobile_fcm_delivery"
PREVIOUS_SCHEMA = "0094_whatsapp_receipt_inbox"


class MobileFcmRelease(ReliabilityRelease):
    def __init__(self, revision: str, root: Path = ROOT) -> None:
        super().__init__(
            revision, root, expected_schema=SCHEMA, previous_schema=PREVIOUS_SCHEMA,
            directory_name="mobile-fcm-release",
            include_frontend=True,
            preserve_release_artifacts=True,
        )


def main() -> int:
    return run_release(MobileFcmRelease, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
