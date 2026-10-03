"""Exact 0128→0129 additive upgrade under a retained executor's writer fence."""

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

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "0128_mcp_document_delivery"
TARGET = "0129_travel_tracker"
POLICY = {
    "version": 1,
    "kind": "travel_tracker_additive_v1",
    "source_schema": SOURCE,
    "target_schema": TARGET,
    "control_enabled": "preserve_existing_state",
    "existing_grants": "retain_without_expansion",
    "read_section_authority": "preserve_existing_state",
    "write_section_authority": "preserve_existing_state",
    "connection_enabled": "preserve_existing_state",
    "existing_requests": "retain_without_expansion",
    "settings": "preserve_existing_state",
    "historical_rows": "preserve_all_fields",
    "new_tables": "empty_before_activation",
    "new_table_runtime_grants": "require_existing_passport_dml_grantees",
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


def verify_sources(root: Path, contract: dict[str, Any]) -> None:
    if (
        not isinstance(contract, dict)
        or set(contract) != set(POLICY) | {"migrations"}
        or any(
            type(contract[key]) is not type(value) or contract[key] != value
            for key, value in POLICY.items()
        )
    ):
        raise ValueError("invalid_tracker_contract")
    entries = contract["migrations"]
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("exact_migration_required")
    entry = entries[0]
    relative = f"backend/alembic/versions/{TARGET}.py"
    if (
        not isinstance(entry, dict)
        or set(entry) != {"revision", "parent", "path", "sha256"}
        or (entry["revision"], entry["parent"], entry["path"]) != (TARGET, SOURCE, relative)
    ):
        raise ValueError("migration_identity_changed")
    path = root / "alembic/versions" / f"{TARGET}.py"
    if (
        path.is_symlink()
        or not path.is_file()
        or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
    ):
        raise ValueError("migration_source_changed")
    identity = {}
    for node in ast.parse(path.read_bytes()).body:
        if isinstance(node, ast.Assign):
            for name in node.targets:
                if isinstance(name, ast.Name) and name.id in {
                    "revision",
                    "down_revision",
                    "branch_labels",
                    "depends_on",
                }:
                    if name.id in identity:
                        raise ValueError("ambiguous_migration_identity")
                    identity[name.id] = ast.literal_eval(node.value)
    if identity != {
        "revision": TARGET,
        "down_revision": SOURCE,
        "branch_labels": None,
        "depends_on": None,
    }:
        raise ValueError("migration_identity_changed")


def retained_catalog(value: dict[str, Any]) -> dict[str, Any]:
    return {
        name: table
        for name, table in value.items()
        if name not in {"travel_tracker", "alembic_version"}
    }


def authority_snapshot(connection: Any, tables: Any) -> dict[str, Any]:
    """Stream every old field, including all current MCP permission columns."""
    from sqlalchemy import text

    quote = connection.dialect.identifier_preparer.quote_identifier
    result = {}
    for name in sorted(tables):
        rows = connection.execute(
            text(
                f"SELECT to_jsonb(record)::text AS original FROM public.{quote(name)} record ORDER BY original"
            ).execution_options(stream_results=True, yield_per=100)
        )
        digest, count = hashlib.sha256(), 0
        try:
            for row in rows:
                digest.update(row[0].encode("utf-8"))
                digest.update(b"\n")
                count += 1
        finally:
            rows.close()
        result[name] = {"count": count, "sha256": digest.hexdigest()}
    return result


def _acl_snapshot(connection: Any, tables: Any) -> dict[str, Any]:
    from sqlalchemy import text

    return {
        name: list(
            connection.execute(
                text(
                    "SELECT pg_get_userbyid(relowner),relacl::text FROM pg_class WHERE oid=to_regclass(:name)"
                ),
                {"name": "public." + name},
            ).one()
        )
        for name in sorted(tables)
    }


def _dml_grants(connection: Any, name: str) -> set[tuple[int, str, bool]]:
    from sqlalchemy import text

    return {
        tuple(row)
        for row in connection.execute(
            text("""
        SELECT a.grantee,a.privilege_type,a.is_grantable
        FROM pg_class c CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
        WHERE c.oid=to_regclass(:name) AND a.grantee<>c.relowner
        AND a.privilege_type IN ('SELECT','INSERT','UPDATE','DELETE')
    """),
            {"name": "public." + name},
        )
    }


def expected_tracker_catalog() -> dict[str, Any]:
    from scripts.mcp_dashboard_write_schema import canonical

    columns = sorted(
        [
            ["passenger_id", "uuid", "NO", None, None, "NO", "NEVER"],
            ["agency_id", "uuid", "NO", None, None, "NO", "NEVER"],
            ["group_id", "uuid", "NO", None, None, "NO", "NEVER"],
            ["visa_applied", "boolean", "NO", None, "false", "NO", "NEVER"],
            ["flight_booked", "boolean", "NO", None, "false", "NO", "NEVER"],
            ["visa_updated_at", "timestamp with time zone", "YES", None, None, "NO", "NEVER"],
            ["flight_updated_at", "timestamp with time zone", "YES", None, None, "NO", "NEVER"],
            ["visa_updated_by", "uuid", "YES", None, None, "NO", "NEVER"],
            ["flight_updated_by", "uuid", "YES", None, None, "NO", "NEVER"],
        ]
    )
    constraints = sorted(
        [
            [
                "travel_tracker_pkey",
                "p",
                True,
                False,
                False,
                canonical("PRIMARY KEY (passenger_id)"),
            ],
            [
                "fk_travel_tracker_passenger_scope",
                "f",
                True,
                False,
                False,
                canonical(
                    "FOREIGN KEY (passenger_id, agency_id, group_id) REFERENCES passport_submissions(id, agency_id, group_id) ON DELETE CASCADE"
                ),
            ],
            [
                "travel_tracker_visa_updated_by_fkey",
                "f",
                True,
                False,
                False,
                canonical("FOREIGN KEY (visa_updated_by) REFERENCES users(id) ON DELETE SET NULL"),
            ],
            [
                "travel_tracker_flight_updated_by_fkey",
                "f",
                True,
                False,
                False,
                canonical(
                    "FOREIGN KEY (flight_updated_by) REFERENCES users(id) ON DELETE SET NULL"
                ),
            ],
        ]
    )
    indexes = sorted(
        [
            [
                "travel_tracker_pkey",
                True,
                True,
                True,
                canonical(
                    "CREATE UNIQUE INDEX travel_tracker_pkey ON public.travel_tracker USING btree (passenger_id)"
                ),
            ],
            [
                "ix_travel_tracker_group_marks",
                True,
                True,
                True,
                canonical(
                    "CREATE INDEX ix_travel_tracker_group_marks ON public.travel_tracker USING btree (agency_id, group_id, visa_applied, flight_booked)"
                ),
            ],
        ]
    )
    return {
        "relation": ["r", False, False, "p"],
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
        "triggers": [],
    }


def verify_schema(connection: Any, schema: str) -> dict[str, Any]:
    from sqlalchemy import text

    from scripts.mcp_dashboard_write_schema import catalog

    actual = catalog(connection)
    if schema == SOURCE:
        if "travel_tracker" in actual:
            raise ValueError("source_has_unreviewed_tracker_table")
    elif schema == TARGET:
        if actual.get("travel_tracker") != expected_tracker_catalog():
            raise ValueError("target_tracker_schema_mismatch")
        if connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM public.travel_tracker)")
        ).scalar_one():
            raise ValueError("tracker_must_be_empty_before_activation")
        if not _dml_grants(connection, "passport_submissions") <= _dml_grants(
            connection, "travel_tracker"
        ):
            raise ValueError("new_tracker_runtime_privileges_missing")
    else:
        raise ValueError("source_schema_mismatch")
    return actual


def apply_upgrade(contract: dict[str, Any]) -> dict[str, Any]:
    verify_sources(ROOT, contract)
    if re.fullmatch(r"[a-f0-9]{64}", os.environ.get("MCP_RELEASE_PROOF_SHA256", "")) is None:
        raise ValueError("release_proof_required")
    os.environ["PGOPTIONS"] = OPTIONS
    sys.path.insert(0, str(ROOT))
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from alembic import command
    from app.core.config.settings import get_settings

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    if tuple(ScriptDirectory.from_config(config).get_heads()) != (TARGET,):
        raise ValueError("candidate_migration_head_mismatch")
    settings = get_settings()
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
            before_catalog = retained_catalog(verify_schema(connection, schema))
            before = authority_snapshot(connection, before_catalog)
            before_acl = _acl_snapshot(connection, before_catalog)
        if schema == SOURCE:
            command.upgrade(config, TARGET)
        with engine.connect() as connection:
            actual = connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalar_one()
            after_catalog = retained_catalog(verify_schema(connection, actual))
            after = authority_snapshot(connection, after_catalog)
            if (
                actual != TARGET
                or before != after
                or before_catalog != after_catalog
                or before_acl != _acl_snapshot(connection, after_catalog)
            ):
                raise ValueError("historical_authority_schema_or_privileges_changed")
        return {
            "status": "upgraded" if schema == SOURCE else "already_at_target",
            "source_schema": SOURCE,
            "target_schema": TARGET,
            "authority_preserved": True,
            "authority": after,
            "old_catalog_sha256": hashlib.sha256(
                json.dumps(after_catalog, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "new_tables_empty": True,
            "runtime_grants_verified": True,
            "automatic_downgrade": False,
        }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-json", required=True)
    arguments = parser.parse_args()
    try:
        if len(arguments.contract_json) > 32768:
            raise ValueError("contract_budget_exceeded")
        print(json.dumps(apply_upgrade(json.loads(arguments.contract_json)), sort_keys=True))
        return 0
    except Exception:
        print('{"status":"failed","reason":"tracker_upgrade_failed","automatic_downgrade":false}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
