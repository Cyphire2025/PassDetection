"""Apply only 0124→0125 in the existing migration identity and writer fence.

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

SOURCE = "0124_mcp_device_access"
TARGET = "0125_mcp_connection_requests"
ROOT = Path(__file__).resolve().parents[1]
OPTIONS = (
    "-c lock_timeout=5000 -c statement_timeout=120000 "
    "-c idle_in_transaction_session_timeout=120000 -c search_path=public"
)
_POLICY = {
    "version": 1,
    "kind": "mcp_admin_approval_v1",
    "source_schema": SOURCE,
    "target_schema": TARGET,
    "read_only_mode": True,
    "allowed_capabilities": ["mcp:read"],
    "control_enabled": "preserve_existing_state",
    "existing_grants": "retain_without_expansion",
    "read_section_authority": "preserve_existing_state",
    "connection_enabled": "preserve_existing_state",
    "pending_requests": "empty_before_activation",
    "recovery": "forward_repair_preserving_target_schema",
    "automatic_downgrade": False,
    "retention": {
        "existing_containers": "retain",
        "source_and_business_files": "retain",
        "backup_and_helper_artifacts": "retain",
        "cleanup": "prohibited",
    },
}

REQUEST_COLUMNS = {
    "id": ("uuid", "NO", None),
    "credential_hash": ("character varying", "NO", 64),
    "source_hash": ("character varying", "NO", 64),
    "comparison_code": ("character varying", "NO", 9),
    "client_id": ("character varying", "NO", 200),
    "redirect_uri": ("character varying", "NO", 1024),
    "resource": ("character varying", "NO", 512),
    "oauth_state": ("character varying", "NO", 512),
    "code_challenge": ("character varying", "NO", 43),
    "requested_capabilities": ("jsonb", "NO", None),
    "approved_capabilities": ("jsonb", "YES", None),
    "name": ("character varying", "NO", 120),
    "device_platform": ("character varying", "NO", 16),
    "status": ("character varying", "NO", 16),
    "created_at": ("timestamp with time zone", "NO", None),
    "expires_at": ("timestamp with time zone", "NO", None),
    "decided_at": ("timestamp with time zone", "YES", None),
    "decision_user_id": ("uuid", "YES", None),
    "security_version": ("integer", "YES", None),
    "mfa_at": ("timestamp with time zone", "YES", None),
    "finalized_at": ("timestamp with time zone", "YES", None),
    "grant_id": ("uuid", "YES", None),
}
REQUEST_CONSTRAINTS = {
    "ck_mcp_request_expiry": ("c", "CHECK ((expires_at > created_at))"),
    "ck_mcp_request_platform": ("c", "CHECK (((device_platform)::text = ANY "
        "((ARRAY['Windows'::character varying, 'macOS'::character varying, "
        "'Other'::character varying])::text[])))"),
    "ck_mcp_request_security_version": ("c", "CHECK (((security_version IS NULL) "
        "OR (security_version >= 1)))"),
    "ck_mcp_request_status": ("c", "CHECK (((status)::text = ANY "
        "((ARRAY['pending'::character varying, 'approved'::character varying, "
        "'rejected'::character varying, 'finalized'::character varying])::text[])))"),
    "mcp_connection_requests_credential_hash_key": ("u", "UNIQUE (credential_hash)"),
    "mcp_connection_requests_decision_user_id_fkey": ("f", "FOREIGN KEY "
        "(decision_user_id) REFERENCES users(id) ON DELETE RESTRICT"),
    "mcp_connection_requests_grant_id_fkey": ("f", "FOREIGN KEY "
        "(grant_id) REFERENCES mcp_grants(id) ON DELETE RESTRICT"),
    "mcp_connection_requests_grant_id_key": ("u", "UNIQUE (grant_id)"),
    "mcp_connection_requests_pkey": ("p", "PRIMARY KEY (id)"),
}
REQUEST_INDEXES = {
    "ix_mcp_requests_source_created": (False, "source_hash, created_at"),
    "ix_mcp_requests_status_created": (False, "status, created_at"),
    "mcp_connection_requests_credential_hash_key": (True, "credential_hash"),
    "mcp_connection_requests_grant_id_key": (True, "grant_id"),
    "mcp_connection_requests_pkey": (True, "id"),
}


def _canonical_definition(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    # Keep literal contents and every parenthesis: removing grouping could
    # accept a predicate with different OR/AND precedence.
    return re.sub(r"'(?:[^']|'')*'|\s+", lambda match: match[0]
                  if match[0].startswith("'") else "", value)


def _verify_request_schema(connection: Any, schema: str) -> None:
    from sqlalchemy import text

    if schema not in {SOURCE, TARGET}:
        raise ValueError("source_schema_mismatch")
    relation = connection.execute(text("""
        SELECT relkind::text,relrowsecurity,relforcerowsecurity,relpersistence::text
        FROM pg_class WHERE oid=to_regclass('public.mcp_connection_requests')
    """)).one_or_none()
    if schema == SOURCE:
        if relation is not None:
            raise ValueError("source_request_table_must_be_absent")
        return
    if relation != ("r", False, False, "p"):
        raise ValueError("target_request_table_mismatch")
    columns = connection.execute(text("""
        SELECT column_name,data_type,is_nullable,character_maximum_length,
            column_default,is_identity,is_generated
        FROM information_schema.columns WHERE table_schema='public'
            AND table_name='mcp_connection_requests' ORDER BY column_name
    """)).all()
    expected = [(name, *value, None, "NO", "NEVER")
                for name, value in sorted(REQUEST_COLUMNS.items())]
    if columns != expected:
        raise ValueError("target_request_columns_mismatch")
    constraints = connection.execute(text("""
        SELECT conname,contype::text,convalidated,condeferrable,condeferred,
            pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conrelid='public.mcp_connection_requests'::regclass ORDER BY conname
    """)).all()
    expected_constraints = [(name, kind, True, False, False,
                             _canonical_definition(definition))
                            for name, (kind, definition)
                            in sorted(REQUEST_CONSTRAINTS.items())]
    actual_constraints = [(name, kind, valid, deferred, initial,
                           _canonical_definition(definition))
                          for name, kind, valid, deferred, initial, definition in constraints]
    if actual_constraints != expected_constraints:
        raise ValueError("target_request_constraints_mismatch")
    indexes = connection.execute(text("""
        SELECT c.relname,i.indisvalid,i.indisready,i.indislive,
            pg_get_indexdef(i.indexrelid) FROM pg_index i
        JOIN pg_class c ON c.oid=i.indexrelid
        WHERE i.indrelid='public.mcp_connection_requests'::regclass ORDER BY c.relname
    """)).all()
    expected_indexes = [(name, True, True, True, _canonical_definition(
        f"CREATE {'UNIQUE ' if unique else ''}INDEX {name} ON "
        f"public.mcp_connection_requests USING btree ({columns})"))
        for name, (unique, columns) in sorted(REQUEST_INDEXES.items())]
    actual_indexes = [(name, valid, ready, live, _canonical_definition(definition))
                      for name, valid, ready, live, definition in indexes]
    if actual_indexes != expected_indexes:
        raise ValueError("target_request_indexes_mismatch")
    if connection.execute(text("""
        SELECT EXISTS (SELECT 1 FROM pg_trigger
            WHERE tgrelid='public.mcp_connection_requests'::regclass AND NOT tgisinternal)
    """)).scalar_one():
        raise ValueError("target_request_trigger_mismatch")


def _require_empty_requests(connection: Any) -> None:
    from sqlalchemy import text

    if connection.execute(text(
        "SELECT EXISTS (SELECT 1 FROM public.mcp_connection_requests)"
    )).scalar_one():
        raise ValueError("pending_requests_must_be_empty_before_activation")


def verify_sources(root: Path, contract: dict[str, Any]) -> None:
    if (
        not isinstance(contract, dict)
        or set(contract) != set(_POLICY) | {"migrations"}
        or any(
            type(contract[key]) is not type(value) or contract[key] != value
            for key, value in _POLICY.items()
        )
    ):
        raise ValueError("invalid_admin_approval_release_contract")
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


def _authority_snapshot(connection: Any) -> dict[str, Any]:
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
    _verify_request_schema(connection, schema)


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
            if schema == TARGET:
                _require_empty_requests(connection)
            enabled = connection.execute(text(
                "SELECT enabled FROM public.mcp_control WHERE id=1"
            )).scalar_one()
            if type(enabled) is not bool:
                raise ValueError("control_state_invalid")
            before = _authority_snapshot(connection)
        if schema == SOURCE:
            command.upgrade(config, TARGET)
        with engine.connect() as connection:
            actual = connection.execute(text(
                "SELECT version_num FROM public.alembic_version"
            )).scalar_one()
            if actual != TARGET:
                raise ValueError("target_schema_mismatch")
            _verify_columns(connection, TARGET)
            _require_empty_requests(connection)
            after = _authority_snapshot(connection)
            if before != after:
                raise ValueError("existing_authority_or_credentials_changed")
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
        print('{"status":"failed","reason":"admin_approval_upgrade_failed",'
              '"automatic_downgrade":false}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
