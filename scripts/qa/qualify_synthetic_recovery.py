"""Restore the current synthetic qualification database and a versioned object.

This is isolated local recovery evidence. It makes no production/off-host/PITR,
volume-representative RPO/RTO, notification or failover claim.
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from datetime import UTC, datetime

from run_qualification_stack import ADMIN, COMPOSE, OUTPUT, ROOT, run

SOURCE = "passdetection_ci_browser"
RESTORED = f"passdetection_ci_recovery_{uuid.uuid4().hex[:12]}"
PG = [*COMPOSE, "exec", "-T", "-e", "PGPASSWORD=qualification-admin-937", "postgres"]
TABLES = ("agencies", "users", "client_groups", "passport_submissions", "audit_logs", "refresh_tokens",
          "public_upload_contact_challenges", "ecr_batches", "ecr_items", "storage_cleanup_jobs")


def query(database: str, sql: str) -> str:
    return subprocess.check_output(
        [*PG, "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", "qualification_admin", "-d", database, "-At", "-c", sql],
        cwd=ROOT, text=True,
    ).strip()


def snapshot(database: str) -> dict[str, str]:
    # Stable full-row digests for synthetic records only. Never export contents,
    # tokens, encrypted MFA material or application credentials in evidence.
    return {table: query(database, f"SELECT count(*) || ':' || md5(coalesce(string_agg(row_to_json(t)::text, '' ORDER BY id), '')) FROM {table} t") for table in TABLES}


def main() -> None:
    started = time.monotonic()
    before = snapshot(SOURCE)
    run([*PG, "pg_dump", "-U", "qualification_admin", "-d", SOURCE, "--format=custom", "--no-owner", "--no-acl", "--file=/tmp/qualification-recovery.dump"], "recovery-dump")
    # Each run creates a new generated target. Even a UUID collision fails at
    # createdb; no existing database is ever dropped or overwritten.
    run([*PG, "createdb", "-U", "qualification_admin", RESTORED], "recovery-create-target")
    run([*PG, "pg_restore", "-U", "qualification_admin", "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl", "--dbname", RESTORED, "/tmp/qualification-recovery.dump"], "recovery-restore")
    after = snapshot(RESTORED)
    if before != after:
        raise RuntimeError("Restored synthetic rows differ from the source snapshot")
    source_revision = query(SOURCE, "SELECT version_num FROM alembic_version ORDER BY version_num")
    if query(RESTORED, "SELECT version_num FROM alembic_version ORDER BY version_num") != source_revision:
        raise RuntimeError("Restored schema revision differs")
    run([*COMPOSE, "run", "--rm", "--no-deps", *ADMIN, "backend", "python", "/workspace/scripts/qa/qualification_object_recovery.py"], "recovery-object-version")
    run([*COMPOSE, "run", "--rm", "--no-deps", *ADMIN, "-e", f"POSTGRES_DB={RESTORED}",
         "backend", "python", "/workspace/scripts/qa/qualification_restored_objects.py"], "recovery-application-objects")
    evidence = {
        "finished_at": datetime.now(UTC).isoformat(), "scope": "isolated synthetic local restore",
        "database": SOURCE, "restored_database": RESTORED, "schema_revision": source_revision,
        "table_count_and_hashes": after, "duration_seconds": round(time.monotonic() - started, 3),
        "object_version_recovery": True, "production_resilience_proof": False,
        "restored_application_object_reconciliation": True,
        "off_host_backup_proof": False, "pitr_proof": False, "representative_rpo_rto_proof": False,
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "recovery-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print("Synthetic current-schema database and object-version recovery passed")


if __name__ == "__main__":
    main()
