"""Rehearse new index/roster DDL on the retained synthetic 100001-row database.

Only the exact loopback CI fixture is accepted. The index-only downgrade drops
two new indexes, never rows or tables. All business tables are streamed and
hashed before/after both a deliberate lock-timeout rejection and the upgrade.
The database remains available afterwards; no cleanup is performed.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config.settings import get_settings  # noqa: E402


def snapshot(engine) -> dict[str, dict[str, int | str]]:
    result = {}
    with engine.connect() as connection:
        tables = (
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename <> 'alembic_version' ORDER BY tablename"
                )
            )
            .scalars()
            .all()
        )
        for table in tables:
            quoted = engine.dialect.identifier_preparer.quote(table)
            # jsonb ordering is stable; omit only the new cache-invalidation
            # column, which has no business meaning and is absent at baseline.
            rows = connection.execution_options(stream_results=True).execute(
                text(
                    f"SELECT (to_jsonb(t) - 'roster_revision')::text AS value "
                    f"FROM {quoted} t ORDER BY value"
                )
            )
            digest, count = hashlib.sha256(), 0
            for row in rows:
                digest.update(row[0].encode())
                digest.update(b"\n")
                count += 1
            result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def alembic(*arguments: str, success: bool = True) -> dict[str, object]:
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-W", "error", "-m", "alembic", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=150,
    )
    output = result.stdout + result.stderr
    if success and result.returncode != 0:
        # Settings/driver failures can include DSNs. Retain local diagnostics
        # under ignored outputs, but do not print them into a public receipt.
        path = ROOT.parent / "outputs/qualification/populated-migration-error.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
        raise RuntimeError(f"Alembic gate failed; inspect {path}")
    if not success and (result.returncode == 0 or "lock timeout" not in output.lower()):
        raise RuntimeError("Held writer did not trigger the expected safe lock-timeout rejection")
    return {
        "arguments": list(arguments),
        "exit_code": result.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def main() -> None:
    settings = get_settings()
    if (
        os.environ.get("POSTGRES_DB") != "passdetection_ci_search_phase2"
        or settings.database.host not in {"127.0.0.1", "localhost"}
        or settings.database.port != 55447
    ):
        raise RuntimeError("Only the retained local search qualification database is allowed")
    engine = create_engine(settings.database.sync_url)
    try:
        with engine.connect() as connection:
            if (
                connection.scalar(text("SELECT current_database()"))
                != "passdetection_ci_search_phase2"
            ):
                raise RuntimeError("Database identity mismatch")
            if (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                != "0110_search_indexes"
            ):
                raise RuntimeError(
                    "The retained fixture must start at the index-only 0110 revision"
                )
        before = snapshot(engine)
        if before["passport_submissions"]["rows"] != 100001:
            raise RuntimeError("The declared 100001-row retained dataset is missing")
        timings = [alembic("downgrade", "0109_dashboard_sessions")]
        if snapshot(engine) != before:
            raise RuntimeError("Index-only downgrade changed business data")
        with engine.connect() as lock, lock.begin():
            lock.execute(text("LOCK TABLE passport_submissions IN ROW EXCLUSIVE MODE"))
            timings.append(alembic("upgrade", "0110_search_indexes", success=False))
        if snapshot(engine) != before:
            raise RuntimeError("Rejected index migration changed business data")
        with engine.connect() as connection:
            if (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                != "0109_dashboard_sessions"
            ):
                raise RuntimeError("Rejected migration advanced the schema revision")
        timings.append(alembic("upgrade", "0110_search_indexes"))
        timings.append(alembic("upgrade", "0111_roster_revision"))
        after = snapshot(engine)
        if after != before:
            raise RuntimeError("Successful migration changed business data")
        timings.append(alembic("check"))
        with engine.connect() as connection:
            revision_count = connection.scalar(
                text("SELECT count(*) FROM client_groups WHERE roster_revision <> 0")
            )
            if revision_count != 0:
                raise RuntimeError("Initial roster migration unexpectedly changed a cache revision")
        receipt = {
            "scope": "local synthetic PostgreSQL 16; no production access",
            "database": "passdetection_ci_search_phase2",
            "result": "passed",
            "populated_passports": 100001,
            "table_digests": after,
            "business_data_unchanged": True,
            "tables_dropped": 0,
            "rows_deleted": 0,
            "lock_timeout_rejection_preserved_revision_and_records": True,
            "schema_metadata_parity": True,
            "timings": timings,
            "limits": "Write-blocking index build; local timing is not a production downtime promise",
        }
        destination = ROOT.parent / "docs/remediation/populated-search-roster-migration.json"
        destination.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(
            json.dumps(
                {key: value for key, value in receipt.items() if key != "table_digests"}, indent=2
            )
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
