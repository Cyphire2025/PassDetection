"""Exact 0125→0128 upgrade under the retained executor's full writer fence."""

import argparse
import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.mcp_dashboard_write_schema import (  # noqa: E402
    NEW_TABLES,
    SOURCE,
    TARGET,
    authority_snapshot,
    retained_catalog,
    verify_schema,
)

CHAIN = ("0126_mcp_section_permissions", "0127_mcp_native_transfers", TARGET)
PROFILE_PATH = "backend/scripts/mcp_dashboard_write_schema.json"
CAPABILITIES = ["mcp:read", "mcp:change", "mcp:upload", "mcp:export", "mcp:communicate"]
POLICY = {
    "version": 1,
    "kind": "mcp_dashboard_write_v1",
    "source_schema": SOURCE,
    "target_schema": TARGET,
    "read_only_mode": False,
    "export_source_row_limit": 100,
    "export_source_byte_limit": 1048576,
    "export_families": [
        "passport_excel",
        "passport_images",
        "tracking_excel",
        "rooming_excel",
        "document_assignments_excel",
    ],
    "allowed_capabilities": CAPABILITIES,
    "control_enabled": "preserve_existing_state",
    "existing_grants": "retain_without_expansion",
    "read_section_authority": "preserve_existing_state",
    "connection_enabled": "preserve_existing_state",
    "existing_requests": "retain_without_expansion",
    "write_authority": "default_denied",
    "new_tables": "empty_before_activation",
    "historical_rows": "preserve_all_fields_except_added_permission_columns",
    "recovery": "forward_repair_preserving_target_schema",
    "automatic_downgrade": False,
    "retention": {
        "existing_containers": "retain",
        "source_and_business_files": "retain",
        "backup_and_helper_artifacts": "retain",
        "cleanup": "prohibited",
    },
}
OPTIONS = "-c lock_timeout=5000 -c statement_timeout=120000 -c idle_in_transaction_session_timeout=120000 -c search_path=public"


def verify_sources(root, contract):
    if (
        not isinstance(contract, dict)
        or set(contract) != set(POLICY) | {"migrations", "schema_profile"}
        or any(type(contract[k]) is not type(v) or contract[k] != v for k, v in POLICY.items())
    ):
        raise ValueError("invalid_dashboard_write_contract")
    parent, entries = SOURCE, contract["migrations"]
    if not isinstance(entries, list) or len(entries) != 3:
        raise ValueError("exact_migration_chain_required")
    for revision, entry in zip(CHAIN, entries, strict=True):
        relative = f"backend/alembic/versions/{revision}.py"
        if (
            not isinstance(entry, dict)
            or set(entry) != {"revision", "parent", "path", "sha256"}
            or (entry["revision"], entry["parent"], entry["path"]) != (revision, parent, relative)
        ):
            raise ValueError("migration_identity_changed")
        path = root / "alembic/versions" / f"{revision}.py"
        if (
            path.is_symlink()
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
        ):
            raise ValueError("migration_source_changed")
        identity = {}
        for node in ast.parse(path.read_bytes()).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {
                        "revision",
                        "down_revision",
                        "branch_labels",
                        "depends_on",
                    }:
                        if target.id in identity:
                            raise ValueError("ambiguous_migration_identity")
                        identity[target.id] = ast.literal_eval(node.value)
        if identity != {
            "revision": revision,
            "down_revision": parent,
            "branch_labels": None,
            "depends_on": None,
        }:
            raise ValueError("migration_identity_changed")
        parent = revision
    bound = contract["schema_profile"]
    profile = root / "scripts/mcp_dashboard_write_schema.json"
    if (
        not isinstance(bound, dict)
        or set(bound) != {"path", "sha256"}
        or bound["path"] != PROFILE_PATH
        or profile.is_symlink()
        or not profile.is_file()
        or hashlib.sha256(profile.read_bytes()).hexdigest() != bound["sha256"]
    ):
        raise ValueError("qualified_schema_profile_changed")
    value = json.loads(profile.read_bytes())
    if (
        set(value) != {"version", "schema", "new_tables", "permissions"}
        or value["version"] != 1
        or value["schema"] != TARGET
        or set(value["new_tables"]) != NEW_TABLES
    ):
        raise ValueError("qualified_schema_profile_invalid")
    return value


def apply_upgrade(contract):
    profile = verify_sources(ROOT, contract)
    if not re.fullmatch(r"[a-f0-9]{64}", os.environ.get("MCP_RELEASE_PROOF_SHA256", "")):
        raise ValueError("release_proof_required")
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from alembic import command
    from app.core.config.settings import get_settings

    settings = get_settings()
    if (
        settings.mcp.read_only_mode
        or set(settings.mcp.effective_capabilities) != set(CAPABILITIES)
        or settings.mcp.export_source_row_limit != 100
        or settings.mcp.export_source_byte_limit != 1048576
        or set(settings.mcp.export_families) != set(POLICY["export_families"])
    ):
        raise ValueError("exact_mixed_code_ceiling_required")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    if tuple(ScriptDirectory.from_config(config).get_heads()) != (TARGET,):
        raise ValueError("candidate_migration_head_mismatch")
    engine = create_engine(
        settings.database.sync_url, poolclass=NullPool, connect_args={"options": OPTIONS}
    )
    try:
        with engine.connect() as connection:
            owner = connection.execute(
                text(
                    "SELECT current_user=pg_get_userbyid(n.nspowner) AND current_user=pg_get_userbyid(d.datdba) AND NOT EXISTS(SELECT 1 FROM pg_tables WHERE schemaname='public' AND tableowner<>current_user) FROM pg_namespace n,pg_database d WHERE n.nspname='public' AND d.datname=current_database()"
                )
            ).scalar_one()
            if owner is not True:
                raise ValueError("existing_migration_identity_required")
            schema = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            before_schema = retained_catalog(verify_schema(connection, schema, profile))
            before = authority_snapshot(connection, before_schema.keys())
        if schema == SOURCE:
            os.environ["PGOPTIONS"] = OPTIONS
            command.upgrade(config, TARGET)
        elif schema != TARGET:
            raise ValueError("source_schema_mismatch")
        with engine.connect() as connection:
            actual = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            after_schema = retained_catalog(verify_schema(connection, actual, profile))
            after = authority_snapshot(connection, after_schema.keys())
            if actual != TARGET or before != after or before_schema != after_schema:
                raise ValueError("historical_authority_or_schema_changed")
        return {
            "status": "upgraded" if schema == SOURCE else "already_at_target",
            "source_schema": SOURCE,
            "target_schema": TARGET,
            "authority_preserved": True,
            "authority": after,
            "old_catalog_sha256": hashlib.sha256(
                json.dumps(after_schema, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "new_tables_empty": True,
            "write_defaults_denied": True,
            "automatic_downgrade": False,
        }
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-json", required=True)
    arguments = parser.parse_args()
    try:
        if len(arguments.contract_json) > 32768:
            raise ValueError("contract_budget_exceeded")
        print(json.dumps(apply_upgrade(json.loads(arguments.contract_json)), sort_keys=True))
        return 0
    except Exception:
        print(
            '{"status":"failed","reason":"dashboard_write_upgrade_failed","automatic_downgrade":false}'
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
