"""Validate the actual populated rehearsal before deriving a Fast receipt."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from release_companies_traveller_contract import CHAIN, SOURCE, TARGET
from release_mcp_database import digest_json

CHECKS = (
    "populated_backup_restored", "historical_rows_catalog_acl_preserved", "runtime_grants_verified",
    "interrupted_resume_verified", "invalid_index_repaired", "wrong_baseline_rejected", "idempotent_target_verified",
)
MARKER = "PASSDETECTION_COMPANIES_REHEARSAL="


def validate_inner(output: str, expected_contract: str) -> dict[str, Any]:
    """Reject incomplete, stale or contradictory proof; never infer success from exit alone."""
    lines = [line[len(MARKER):] for line in output.splitlines() if line.startswith(MARKER)]
    if len(lines) != 1 or len(lines[0].encode()) > 60 * 1024:
        raise ValueError("Exactly one bounded migration receipt is required")
    envelope = json.loads(lines[0])
    if envelope.get("source_contract_sha256") != expected_contract:
        raise ValueError("Candidate migration source differs from the selected contract")
    value = envelope["rehearsal"]
    if (value.get("version") != 1 or value.get("source_revision") != SOURCE
            or value.get("target_revision") != TARGET or value.get("server_major") != 16
            or value.get("production_release_authorization") is not False):
        raise ValueError("Rehearsal schema, PostgreSQL version or scope differs")
    required = ("preserved_historical_rows_catalog_acl", "new_tables_empty_before_activation",
                "runtime_grants_nonempty", "wrong_baseline_rejected_before_ddl", "invalid_concurrent_index_repaired",
                "company_backfill_rollback_verified")
    if any(value.get(key) is not True for key in required):
        raise ValueError("A required preservation or failure scenario was not proven")
    if value.get("company_backfill_rollback") != {"exit_code": 74, "rolled_back_revision": CHAIN[0]}:
        raise ValueError("The failed company backfill must restore the complete original revision")
    counts = value["historical_row_counts"]
    if counts.get("whatsapp_broadcast_rejected_contacts") != 699 or counts.get("whatsapp_broadcast_recipients") != 1:
        raise ValueError("The full 700-person durable roster was not exercised")
    dump = value["dump"]
    if (type(dump.get("bytes")) is not int or dump["bytes"] <= 0
            or re.fullmatch(r"[a-f0-9]{64}", str(dump.get("sha256", ""))) is None):
        raise ValueError("A nonempty populated backup is required")
    clients = value["backup_clients"]
    if set(clients) != {"pg_dump", "pg_restore"} or any(
            re.fullmatch(r"pg_(?:dump|restore) \(PostgreSQL\) 16(?:\.\d+)?(?: .*)?", version) is None
            for version in clients.values()):
        raise ValueError("Both backup clients must be PostgreSQL 16")
    baseline, resume, noop = (value[key] for key in ("original_preservation_baseline", "resume", "noop"))
    baseline_hash = baseline.get("preservation_sha256", "")
    if (baseline.get("status") != "baseline_captured" or re.fullmatch(r"[a-f0-9]{64}", baseline_hash) is None
            or value.get("interruption") != {"exit_code": 73, "interrupted_before": CHAIN[2]}
            or resume.get("status") != "upgraded" or resume.get("started_schema") != CHAIN[1]
            or resume.get("executed_revisions") != list(CHAIN[2:])
            or noop.get("status") != "already_at_target" or noop.get("started_schema") != TARGET
            or noop.get("executed_revisions") != []):
        raise ValueError("Checkpoint interruption, forward resume and target idempotency must be proven")
    for proof in (baseline, resume, noop):
        if (proof.get("source_schema") != SOURCE or proof.get("target_schema") != TARGET
                or proof.get("automatic_downgrade") is not False
                or proof.get("preservation_sha256") != baseline_hash):
            raise ValueError("Preservation baseline changed across migration phases")
    if any(proof.get(key) is not True for proof in (resume, noop)
           for key in ("new_tables_empty", "runtime_grants_verified")):
        raise ValueError("Target table and runtime grant invariants were not proven")
    return {"checks": dict.fromkeys(CHECKS, True), "fixture_person_count": 700,
            "company_backfill_rollback_verified": True,
            "inner_rehearsal_sha256": digest_json(value), "populated_backup": dump,
            "preservation_sha256": baseline_hash, "backup_clients": clients}
