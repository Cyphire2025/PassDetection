"""Apply only the reviewed read-only migration in a retained, fenced helper.

The host executor owns the live writer fence, backup and exact DB/image binding.
This helper checks its packaged source and existing migration identity. It never
enables the singleton, changes grants, drops schema, or prints raw failures.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path

SOURCE = "0122_mcp_gc_push"
TARGET = "0123_mcp_read_sections"
ROOT = Path(__file__).resolve().parents[1]
OPTIONS = (
    "-c lock_timeout=5000 -c statement_timeout=120000 -c idle_in_transaction_session_timeout=120000"
)


def verify_sources(root: Path, contract: dict) -> None:
    expected = {
        "version": 1,
        "kind": "mcp_read_only_v1",
        "source_schema": SOURCE,
        "target_schema": TARGET,
        "read_only_mode": True,
        "allowed_capabilities": ["mcp:read"],
        "control_enabled": "preserve_existing_state",
        "existing_grants": "retain_without_expansion",
        "recovery": "forward_repair_preserving_target_schema",
        "automatic_downgrade": False,
        "retention": {
            "existing_containers": "retain",
            "source_and_business_files": "retain",
            "backup_and_helper_artifacts": "retain",
            "cleanup": "prohibited",
        },
    }
    if (
        not isinstance(contract, dict)
        or set(contract) != set(expected) | {"migrations"}
        or any(
            type(contract[key]) is not type(value) or contract[key] != value
            for key, value in expected.items()
        )
    ):
        raise ValueError("invalid_read_only_release_contract")
    entries = contract["migrations"]
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("invalid_migration_chain")
    entry = entries[0]
    relative = f"backend/alembic/versions/{TARGET}.py"
    if (
        not isinstance(entry, dict)
        or set(entry) != {"revision", "parent", "path", "sha256"}
        or entry["revision"] != TARGET
        or entry["parent"] != SOURCE
        or entry["path"] != relative
    ):
        raise ValueError("invalid_migration_identity")
    path = root / "alembic/versions" / f"{TARGET}.py"
    if path.is_symlink() or not path.is_file():
        raise ValueError("invalid_migration_source")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError("migration_source_changed")
    identity = {}
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign):
            for key in node.targets:
                if isinstance(key, ast.Name) and key.id in {
                    "revision",
                    "down_revision",
                    "branch_labels",
                    "depends_on",
                }:
                    if key.id in identity:
                        raise ValueError("ambiguous_migration_identity")
                    identity[key.id] = ast.literal_eval(node.value)
    if identity != {
        "revision": TARGET,
        "down_revision": SOURCE,
        "branch_labels": None,
        "depends_on": None,
    }:
        raise ValueError("migration_identity_changed")


def apply_upgrade(contract: dict) -> dict[str, str]:
    verify_sources(ROOT, contract)
    if not re.fullmatch(r"[a-f0-9]{64}", os.environ.get("MCP_RELEASE_PROOF_SHA256", "")):
        raise ValueError("release_proof_required")
    os.environ["PGOPTIONS"] = OPTIONS
    sys.path.insert(0, str(ROOT))
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from alembic import command
    from app.core.config.settings import get_settings

    settings = get_settings()
    if not settings.mcp.read_only_mode or settings.mcp.effective_capabilities != ["mcp:read"]:
        raise ValueError("read_only_deployment_required")
    engine = create_engine(
        settings.database.sync_url, poolclass=NullPool, connect_args={"options": OPTIONS}
    )
    try:
        with engine.connect() as connection:
            owner = connection.execute(
                text(
                    "SELECT current_user = pg_get_userbyid(n.nspowner) AND current_user = pg_get_userbyid(d.datdba) "
                    "AND NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tableowner <> current_user) "
                    "FROM pg_namespace n, pg_database d WHERE n.nspname='public' AND d.datname=current_database()"
                )
            ).scalar_one()
            if owner is not True:
                raise ValueError("existing_migration_identity_required")
            schema = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            enabled = connection.execute(
                text("SELECT enabled FROM public.mcp_control WHERE id=1")
            ).scalar_one()
        if schema not in {SOURCE, TARGET}:
            raise ValueError("source_schema_mismatch")
        if schema == SOURCE:
            config = Config(str(ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "alembic"))
            command.upgrade(config, TARGET)
        with engine.connect() as connection:
            actual = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            preserved = connection.execute(
                text("SELECT enabled FROM public.mcp_control WHERE id=1")
            ).scalar_one()
        if actual != TARGET or type(enabled) is not bool or preserved is not enabled:
            raise ValueError("target_schema_or_control_preservation_invalid")
        return {
            "status": "already_at_target" if schema == TARGET else "upgraded",
            "source_schema": SOURCE,
            "target_schema": TARGET,
        }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-json", required=True)
    args = parser.parse_args()
    try:
        if len(args.contract_json) > 32768:
            raise ValueError("contract_too_large")
        print(json.dumps(apply_upgrade(json.loads(args.contract_json)), sort_keys=True))
        return 0
    except Exception:
        print('{"status":"failed","reason":"read_only_upgrade_failed","automatic_downgrade":false}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
