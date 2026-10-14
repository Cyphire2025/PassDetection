"""Apply the exact 0135→0138 chain inside a retained, writer-fenced helper.

Each revision owns its transaction. Resume requires the original 0135 backup
and preservation baseline. No automatic downgrade, enrollment or activation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.companies_traveller_reuse_release import (  # noqa: E402
    POLICY as POLICY,
)
from scripts.companies_traveller_reuse_release import (  # noqa: E402
    SOURCE,
    TARGET,
    remaining_revisions,
    verify_sources,
)

OPTIONS = "-c lock_timeout=5000 -c statement_timeout=120000 -c idle_in_transaction_session_timeout=120000 -c search_path=public -c work_mem=16MB"


def run_revisions(config: Any, schema: str, upgrade: Any, read_schema: Any) -> None:
    """Commit and verify each frozen revision before advancing its checkpoint."""
    for revision in remaining_revisions(schema):
        upgrade(config, revision)
        if read_schema() != revision:
            raise ValueError("migration_checkpoint_mismatch")


def preservation_digest(snapshot: dict[str, Any]) -> str:
    """Bind the bounded-memory row, catalog and ACL snapshot deterministically."""
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def expected_baseline(*, capture_baseline: bool) -> str | None:
    if capture_baseline:
        return None
    value = os.environ.get("MCP_RELEASE_BASELINE_SHA256", "")
    if re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError("original_preservation_baseline_required")
    return value


def check_baseline(snapshot: dict[str, Any], expected: str) -> None:
    if preservation_digest(snapshot) != expected:
        raise ValueError("original_historical_rows_authority_catalog_or_acl_changed")


def apply_upgrade(contract: dict[str, Any], *, capture_baseline: bool = False) -> dict[str, Any]:
    verify_sources(ROOT, contract)
    proof = os.environ.get("MCP_RELEASE_PROOF_SHA256", "")
    if re.fullmatch(r"[a-f0-9]{64}", proof) is None:
        raise ValueError("release_proof_required")
    expected = expected_baseline(capture_baseline=capture_baseline)
    os.environ["PGOPTIONS"] = OPTIONS
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from alembic import command
    from app.core.config.settings import get_settings
    from scripts.companies_traveller_release_schema import preservation_snapshot, verify_schema

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    if tuple(ScriptDirectory.from_config(config).get_heads()) != (TARGET,):
        raise ValueError("candidate_migration_head_mismatch")
    engine = create_engine(get_settings().database.sync_url, poolclass=NullPool, connect_args={"options": OPTIONS})
    try:
        def read_schema() -> str:
            with engine.connect() as connection:
                schema = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
                verify_schema(connection, ROOT, schema)
                return str(schema)

        with engine.connect() as connection:
            # PostgreSQL 15+ assigns public to pg_database_owner, whose sole
            # implicit member is this database's owner. No broader role grant qualifies.
            owner = connection.execute(text(
                "SELECT current_user=pg_get_userbyid(d.datdba) "
                "AND (current_user=pg_get_userbyid(n.nspowner) OR pg_get_userbyid(n.nspowner)='pg_database_owner') "
                "AND NOT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public' AND tableowner<>current_user) "
                "FROM pg_namespace n,pg_database d WHERE n.nspname='public' AND d.datname=current_database()"
            )).scalar_one()
            if owner is not True:
                raise ValueError("existing_migration_identity_required")
            schema = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
            before = preservation_snapshot(connection, ROOT, schema)
        if capture_baseline:
            if schema != SOURCE:
                raise ValueError("original_source_required_for_baseline")
            return {
                "status": "baseline_captured", "source_schema": SOURCE, "target_schema": TARGET,
                "preservation_sha256": preservation_digest(before), "release_proof_sha256": proof,
                "automatic_downgrade": False,
            }
        assert expected is not None  # Required before opening the database.
        check_baseline(before, expected)
        run_revisions(config, schema, command.upgrade, read_schema)
        with engine.connect() as connection:
            actual = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
            after = preservation_snapshot(connection, ROOT, actual)
            if actual != TARGET:
                raise ValueError("historical_rows_authority_catalog_or_acl_changed")
            check_baseline(after, expected)
        return {
            "status": "already_at_target" if schema == TARGET else "upgraded",
            "started_schema": schema, "source_schema": SOURCE, "target_schema": TARGET,
            "executed_revisions": list(remaining_revisions(schema)),
            "preservation_sha256": expected, "release_proof_sha256": proof,
            "new_tables_empty": True, "runtime_grants_verified": True,
            "automatic_downgrade": False,
        }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-json", required=True)
    parser.add_argument("--capture-baseline", action="store_true")
    arguments = parser.parse_args()
    try:
        if len(arguments.contract_json) > 32768:
            raise ValueError("contract_budget_exceeded")
        print(json.dumps(apply_upgrade(json.loads(arguments.contract_json),
            capture_baseline=arguments.capture_baseline), sort_keys=True))
        return 0
    except Exception:
        print('{"status":"failed","reason":"companies_traveller_upgrade_failed","automatic_downgrade":false}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
