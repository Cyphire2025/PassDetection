"""Apply only 0123→0124 in the existing migration identity and writer fence.

The host executor owns the backup, exact image/database binding and writer
drain. This helper preserves control, grants and issued credentials, supports
idempotent forward retry, and never downgrades or manages containers/resources.
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

SOURCE = "0123_mcp_read_sections"
TARGET = "0124_mcp_device_access"
ROOT = Path(__file__).resolve().parents[1]
OPTIONS = (
    "-c lock_timeout=5000 -c statement_timeout=120000 -c idle_in_transaction_session_timeout=120000"
)
_POLICY = {
    "version": 1,
    "kind": "mcp_direct_devices_v1",
    "source_schema": SOURCE,
    "target_schema": TARGET,
    "read_only_mode": True,
    "allowed_capabilities": ["mcp:read"],
    "control_enabled": "preserve_existing_state",
    "existing_grants": "retain_without_expansion",
    "read_section_authority": "preserve_existing_state",
    "connection_enabled": "existing_grants_remain_enabled",
    "recovery": "forward_repair_preserving_target_schema",
    "automatic_downgrade": False,
    "retention": {
        "existing_containers": "retain",
        "source_and_business_files": "retain",
        "backup_and_helper_artifacts": "retain",
        "cleanup": "prohibited",
    },
}


def verify_sources(root: Path, contract: dict[str, Any]) -> None:
    if (
        not isinstance(contract, dict)
        or set(contract) != set(_POLICY) | {"migrations"}
        or any(
            type(contract[key]) is not type(value) or contract[key] != value
            for key, value in _POLICY.items()
        )
    ):
        raise ValueError("invalid_direct_devices_release_contract")
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
        or not isinstance(entry["sha256"], str)
        or re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]) is None
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
                    "revision", "down_revision", "branch_labels", "depends_on",
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


def _authority_snapshot(connection: Any, *, legacy_projection: bool) -> dict[str, Any]:
    """Stream fixed authority projections; never expose private row contents."""
    from sqlalchemy import text

    result = {}
    for table, order in (
        ("mcp_control", "id"),
        ("mcp_grants", "id"),
        ("mcp_tokens", "token_hash"),
        ("mcp_authorization_codes", "code_hash"),
    ):
        projection = "to_jsonb(record)"
        if table == "mcp_grants" and legacy_projection:
            projection += " - 'enabled' - 'device_platform'"
        digest, count = hashlib.sha256(), 0
        rows = connection.execute(text(
            f"SELECT ({projection})::text FROM public.{table} record ORDER BY {order}"
        ).execution_options(stream_results=True, yield_per=100))
        try:
            for row in rows:
                digest.update(row[0].encode("utf-8"))
                digest.update(b"\n")
                count += 1
        finally:
            rows.close()
        result[table] = {"count": count, "sha256": digest.hexdigest()}
    return result


def _verify_columns(connection: Any, schema: str) -> None:
    from sqlalchemy import text

    rows = connection.execute(text("""
        SELECT column_name,data_type,is_nullable,column_default,character_maximum_length
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='mcp_grants'
          AND column_name IN ('enabled','device_platform') ORDER BY column_name
    """)).all()
    if schema == SOURCE:
        if rows:
            raise ValueError("source_schema_columns_mismatch")
        return
    if rows != [
        ("device_platform", "character varying", "YES", None, 16),
        ("enabled", "boolean", "NO", "true", None),
    ]:
        raise ValueError("target_schema_columns_mismatch")
    constraint = connection.execute(text("""
        SELECT convalidated,pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conrelid='public.mcp_grants'::regclass
          AND conname='ck_mcp_grant_device_platform' AND contype='c'
    """)).one_or_none()
    if constraint is None or constraint[0] is not True:
        raise ValueError("target_platform_constraint_missing")
    if not _valid_platform_constraint(constraint[1]):
        raise ValueError("target_platform_constraint_mismatch")


def _valid_platform_constraint(definition: Any) -> bool:
    """Accept only the complete null-or-exact-label predicate PostgreSQL emits.

    PostgreSQL renders IN as = ANY, with harmless parentheses and text/varchar
    casts varying by server version. There are only two OR operands here; removing
    their redundant parentheses cannot change precedence. Any extra predicate,
    changed label, operator, column, or expression fails the complete match.
    """
    if not isinstance(definition, str):
        return False
    # Preserve quoted label contents exactly; whitespace inside a label is data.
    normalized = re.sub(
        r"'(?:[^']|'')*'|[()\s]+",
        lambda match: match[0] if match[0].startswith("'") else "",
        definition,
    )
    label_type = r"(?:::charactervarying|::text)"
    pattern = (
        r"CHECKdevice_platformISNULLORdevice_platform(?:::text)?=ANYARRAY\["
        rf"'Windows'{label_type},'macOS'{label_type},'Other'{label_type}"
        r"\](?:::text\[\])?"
    )
    return re.fullmatch(pattern, normalized) is not None


def apply_upgrade(contract: dict[str, Any]) -> dict[str, Any]:
    verify_sources(ROOT, contract)
    if not re.fullmatch(r"[a-f0-9]{64}", os.environ.get("MCP_RELEASE_PROOF_SHA256", "")):
        raise ValueError("release_proof_required")
    os.environ["PGOPTIONS"] = OPTIONS
    sys.path.insert(0, str(ROOT))
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    from alembic import command
    from app.core.config.settings import get_settings

    settings = get_settings()
    if not settings.mcp.read_only_mode or settings.mcp.effective_capabilities != ["mcp:read"]:
        raise ValueError("read_only_deployment_required")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    if tuple(scripts.get_heads()) != (TARGET,):
        raise ValueError("candidate_migration_head_mismatch")
    engine = create_engine(
        settings.database.sync_url, poolclass=NullPool, connect_args={"options": OPTIONS}
    )
    try:
        with engine.connect() as connection:
            owner = connection.execute(text(
                "SELECT current_user = pg_get_userbyid(n.nspowner) "
                "AND current_user = pg_get_userbyid(d.datdba) "
                "AND NOT EXISTS (SELECT 1 FROM pg_tables "
                "WHERE schemaname='public' AND tableowner <> current_user) "
                "FROM pg_namespace n, pg_database d "
                "WHERE n.nspname='public' AND d.datname=current_database()"
            )).scalar_one()
            if owner is not True:
                raise ValueError("existing_migration_identity_required")
            schema = connection.execute(text(
                "SELECT version_num FROM public.alembic_version"
            )).scalar_one()
            if schema not in {SOURCE, TARGET}:
                raise ValueError("source_schema_mismatch")
            _verify_columns(connection, schema)
            enabled = connection.execute(text(
                "SELECT enabled FROM public.mcp_control WHERE id=1"
            )).scalar_one()
            if type(enabled) is not bool:
                raise ValueError("control_state_invalid")
            before = _authority_snapshot(connection, legacy_projection=schema == SOURCE)
        if schema == SOURCE:
            command.upgrade(config, TARGET)
        with engine.connect() as connection:
            actual = connection.execute(text(
                "SELECT version_num FROM public.alembic_version"
            )).scalar_one()
            if actual != TARGET:
                raise ValueError("target_schema_mismatch")
            _verify_columns(connection, TARGET)
            after = _authority_snapshot(connection, legacy_projection=schema == SOURCE)
            if before != after:
                raise ValueError("existing_authority_or_credentials_changed")
            if schema == SOURCE and connection.execute(text(
                "SELECT EXISTS (SELECT 1 FROM public.mcp_grants "
                "WHERE enabled IS NOT TRUE OR device_platform IS NOT NULL)"
            )).scalar_one():
                raise ValueError("legacy_connection_defaults_invalid")
        return {
            "status": "already_at_target" if schema == TARGET else "upgraded",
            "source_schema": SOURCE,
            "target_schema": TARGET,
            "authority_preserved": True,
            "authority": after,
            "automatic_downgrade": False,
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
        print('{"status":"failed","reason":"direct_devices_upgrade_failed",'
              '"automatic_downgrade":false}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
