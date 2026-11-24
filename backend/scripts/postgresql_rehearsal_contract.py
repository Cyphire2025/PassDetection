"""PostgreSQL synthetic rehearsal contract owner."""

from __future__ import annotations

import json
import re
from pathlib import Path

PREVIOUS_RELEASE_REVISION = "0085_platform_retention_controls"


EXPECTED_HEAD_REVISION = json.loads(
    (Path(__file__).resolve().parents[1] / "app/core/config/release_manifest.json").read_text(
        encoding="utf-8"
    )
)["schema_revision"]


SAFE_DATABASE_NAME = re.compile(r"^passdetection_ci_[a-z0-9_]+$")


PROTECTED_DATABASE_NAMES = frozenset({"postgres", "template0", "template1"})


DESTRUCTIVE_ACKNOWLEDGEMENT = "MIGRATION_REHEARSAL_ALLOW_EPHEMERAL_DATABASE_DELETION"


IDS = {
    "agency_a": "10000000-0000-0000-0000-000000000001",
    "agency_b": "10000000-0000-0000-0000-000000000002",
    "admin_a": "20000000-0000-0000-0000-000000000001",
    "coordinator_a": "20000000-0000-0000-0000-000000000002",
    "coordinator_b": "20000000-0000-0000-0000-000000000003",
    "group_a": "30000000-0000-0000-0000-000000000001",
    "group_b": "30000000-0000-0000-0000-000000000002",
    "passenger_a": "40000000-0000-0000-0000-000000000001",
    "session_a": "50000000-0000-0000-0000-000000000001",
    "attendance_a": "60000000-0000-0000-0000-000000000001",
    "hotel_a": "70000000-0000-0000-0000-000000000001",
    "gc_access_a": "80000000-0000-0000-0000-000000000001",
    "gc_access_b": "80000000-0000-0000-0000-000000000002",
    "closeout_a": "90000000-0000-0000-0000-000000000001",
    "audit_a": "a0000000-0000-0000-0000-000000000001",
    "identity_token_a": "b0000000-0000-0000-0000-000000000001",
    "gallery_a": "c0000000-0000-0000-0000-000000000001",
    "invalid_closeout": "d0000000-0000-0000-0000-000000000001",
    "invalid_gallery": "d0000000-0000-0000-0000-000000000002",
}


PRESERVED_TABLES = (
    "agencies",
    "users",
    "user_security_states",
    "client_groups",
    "passport_submissions",
    "attendance_sessions",
    "attendance_records",
    "attendance_closeout_checkpoints",
    "rooming_hotels",
    "gc_group_access",
    "audit_logs",
    "identity_action_tokens",
)
