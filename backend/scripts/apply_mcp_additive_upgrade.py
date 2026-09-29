"""Exact MCP additive upgrade inside a retained, operator-fenced maintenance helper.

The release executor supplies the existing migration identity and verifies the
live writer/database/container bindings. No credentials or raw exceptions print.
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
from typing import Any

SOURCE = "0113_document_follow_up"
CHAIN = (
    "0114_mcp_connections",
    "0115_mcp_workflows",
    "0116_mcp_communications",
    "0117_mcp_dispatch_origin",
    "0118_mcp_pdf_ingestion",
    "0119_mcp_contact_imports",
    "0120_mcp_whatsapp_media",
    "0121_whatsapp_send_intents",
    "0122_mcp_gc_push",
)
OPTIONS = (
    "-c lock_timeout=5000 -c statement_timeout=120000 -c idle_in_transaction_session_timeout=120000"
)
ROOT = Path(__file__).resolve().parents[1]


def verify_sources(root: Path, contract: dict[str, Any]) -> None:
    if (
        not isinstance(contract, dict)
        or set(contract)
        != {
            "version",
            "kind",
            "source_schema",
            "target_schema",
            "migrations",
            "initial_mcp_enabled",
            "initial_allowed_capabilities",
            "recovery",
            "automatic_downgrade",
            "retention",
        }
        or type(contract.get("version")) is not int
        or contract["version"] != 1
        or contract.get("kind") != "mcp_additive_v1"
        or contract.get("source_schema") != SOURCE
        or contract.get("target_schema") != CHAIN[-1]
        or contract.get("automatic_downgrade") is not False
        or contract.get("initial_mcp_enabled") is not False
        or contract.get("initial_allowed_capabilities") != ["mcp:read", "mcp:export"]
        or contract.get("retention")
        != {
            "existing_containers": "retain",
            "source_and_business_files": "retain",
            "backup_and_helper_artifacts": "retain",
            "cleanup": "prohibited",
        }
        or contract.get("recovery") != "forward_repair_preserving_target_schema"
    ):
        raise ValueError("invalid_release_contract")
    entries = contract.get("migrations")
    if not isinstance(entries, list) or len(entries) != len(CHAIN):
        raise ValueError("invalid_migration_chain")
    parent = SOURCE
    for entry, revision in zip(entries, CHAIN, strict=True):
        relative = f"backend/alembic/versions/{revision}.py"
        if (
            not isinstance(entry, dict)
            or set(entry) != {"revision", "parent", "path", "sha256"}
            or entry.get("revision") != revision
            or entry.get("parent") != parent
            or entry.get("path") != relative
        ):
            raise ValueError("invalid_migration_chain")
        path = root / "alembic" / "versions" / f"{revision}.py"
        if path.is_symlink() or not path.is_file():
            raise ValueError("invalid_migration_source")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
            raise ValueError("migration_source_changed")
        identities = {}
        for node in ast.parse(raw).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {
                        "revision",
                        "down_revision",
                        "branch_labels",
                        "depends_on",
                    }:
                        if target.id in identities:
                            raise ValueError("ambiguous_migration_identity")
                        identities[target.id] = ast.literal_eval(node.value)
        if identities != {
            "revision": revision,
            "down_revision": parent,
            "branch_labels": None,
            "depends_on": None,
        }:
            raise ValueError("migration_identity_changed")
        parent = revision


def apply_upgrade(contract: dict[str, Any]) -> dict[str, str]:
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
    engine = create_engine(
        settings.database.sync_url, poolclass=NullPool, connect_args={"options": OPTIONS}
    )
    try:
        with engine.connect() as connection:
            owner = connection.execute(
                text(
                    "SELECT current_user = pg_get_userbyid(n.nspowner) AND current_user = pg_get_userbyid(d.datdba) AND NOT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname='public' AND tableowner <> current_user) FROM pg_namespace n, pg_database d WHERE n.nspname='public' AND d.datname=current_database()"
                )
            ).scalar_one()
            if owner is not True:
                raise ValueError("existing_migration_identity_required")
            schema = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
        if schema not in {SOURCE, CHAIN[-1]}:
            raise ValueError("source_schema_mismatch")
        if schema == SOURCE:
            config = Config(str(ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "alembic"))
            command.upgrade(config, CHAIN[-1])
        with engine.connect() as connection:
            actual = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            disabled = connection.execute(
                text("SELECT enabled FROM public.mcp_control WHERE id=1")
            ).scalar_one()
        if actual != CHAIN[-1] or disabled is not False:
            raise ValueError("target_schema_or_initial_control_invalid")
        return {
            "status": "already_at_target" if schema == CHAIN[-1] else "upgraded",
            "source_schema": SOURCE,
            "target_schema": CHAIN[-1],
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
        result = apply_upgrade(json.loads(args.contract_json))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print('{"status":"failed","reason":"additive_upgrade_failed","automatic_downgrade":false}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
