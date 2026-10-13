"""Preserve every existing row and privilege during the fenced 0133->0135 update.

Historical hashing is O(R log R) database sort work and O(100 rows) client memory.
It is maintenance-only, with a 120-second statement limit and 16 MiB work_mem.
Only exact new indexes, tables, constraints, one source-date projection and
revoked-manager nullability are normalized. Every original column remains hashed.
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text

from scripts.companies_traveller_reuse_release import CHAIN, SOURCE, remaining_revisions
from scripts.mcp_dashboard_write_schema import catalog
from scripts.release_travel_tracker_upgrade import _acl_snapshot, _dml_grants

MANAGER_TABLE = "client_manager_group_assignments"
MANAGER_CONSTRAINTS = {
    "fk_client_manager_assignment_retained_profile":
        "FOREIGN KEY (profile_id, agency_id) REFERENCES client_manager_profiles(id, agency_id) ON DELETE CASCADE",
    "fk_client_manager_assignment_retained_group":
        "FOREIGN KEY (gc_group_access_id, agency_id, group_id) REFERENCES gc_group_access(id, agency_id, group_id) ON DELETE CASCADE",
    "ck_client_manager_assignment_active_organization":
        "CHECK (NOT is_active OR organization_id IS NOT NULL)",
}
SEEK_INDEXES = {
    "traveller_profiles": ("ix_traveller_profile_created_seek", "agency_id,company_id,created_at,id"),
    "traveller_document_revisions": ("ix_traveller_document_person_seek", "agency_id,company_id,traveller_id,created_at,id"),
    "traveller_document_assets": ("ix_traveller_asset_company_seek", "agency_id,company_id,id"),
    "traveller_match_cases": ("ix_traveller_match_person_source", "agency_id,company_id,traveller_id,status,source_kind,source_created_at,id"),
    "traveller_reconciliation_jobs": ("ix_traveller_reconciliation_advance", "available_at,id"),
    MANAGER_TABLE: ("ix_client_manager_assignment_company", "agency_id,organization_id,id"),
}
_ADVANCE_PREDICATE = "WHEREstatus::text='succeeded'::textANDlast_error_code::text='chain_advance_pending'::text"
SOURCE_PROJECTION = "source_created_at"


def new_tables(backend: Path, schema: str) -> set[str]:
    """Read only hash-bound frozen DDL; never import mutable application models."""
    remaining_revisions(schema)
    if schema == SOURCE:
        return set()
    names: set[str] = set()
    source = backend / "alembic/versions" / f"{CHAIN[0]}.py"
    for node in ast.parse(source.read_bytes()).body:
        if isinstance(node, ast.Assign) and any(isinstance(name, ast.Name) and name.id == "DDL" for name in node.targets):
            for statement in ast.literal_eval(node.value):
                matched = re.match(r"CREATE TABLE ([a-z_]+)\s*\(", statement)
                if matched:
                    names.add(matched[1])
    if names != {"company_data_export_jobs", "company_data_export_parts"}:
        raise ValueError("exact_export_tables_required")
    return names


def retained_catalog(value: dict[str, Any], all_new_tables: set[str]) -> dict[str, Any]:
    result = {}
    for name, table in value.items():
        if name in all_new_tables or name == "alembic_version":
            continue
        columns = [list(row) for row in table["columns"]]
        if name == "traveller_match_cases":
            columns = [row for row in columns if row[0] != SOURCE_PROJECTION]
        if name == MANAGER_TABLE:
            # verify_schema checks the exact source/target nullability first.
            for row in columns:
                if row[0] == "organization_id":
                    row[2] = "NO"
        result[name] = {
            **table, "columns": columns,
            "constraints": [row for row in table["constraints"] if not (
                name == MANAGER_TABLE and row[0] in MANAGER_CONSTRAINTS)],
            "indexes": [row for row in table["indexes"] if not (
                name in SEEK_INDEXES and row[0] == SEEK_INDEXES[name][0])],
        }
    return result


def authority_snapshot(connection: Any, tables: dict[str, Any]) -> dict[str, Any]:
    result = {}
    quote = connection.dialect.identifier_preparer.quote_identifier
    for name in sorted(tables):
        projection = "to_jsonb(record)"
        if name == "traveller_match_cases":
            projection += f" - '{SOURCE_PROJECTION}'"
        rows = connection.execute(text(
            f"SELECT ({projection})::text AS original FROM public.{quote(name)} record ORDER BY original"
        ).execution_options(stream_results=True, yield_per=100))
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


def _normalize_constraint(value: str) -> str:
    return re.sub(r"[\s()]", "", value)


def verify_manager_checkpoint(actual: dict[str, Any], schema: str) -> None:
    table = actual[MANAGER_TABLE]
    target = schema == CHAIN[1]
    columns = [row for row in table["columns"] if row[0] == "organization_id"]
    if len(columns) != 1 or columns[0][2] != ("YES" if target else "NO"):
        raise ValueError("unexpected_manager_company_nullability")
    constraints = {row[0]: row for row in table["constraints"] if row[0] in MANAGER_CONSTRAINTS}
    if set(constraints) != (set(MANAGER_CONSTRAINTS) if target else set()):
        raise ValueError("unexpected_manager_constraint_checkpoint")
    for name, row in constraints.items():
        if (row[2:5] != [True, False, False]
                or _normalize_constraint(row[-1]) != _normalize_constraint(MANAGER_CONSTRAINTS[name])):
            raise ValueError("manager_scope_constraint_changed")


def verify_schema(connection: Any, backend: Path, schema: str) -> dict[str, Any]:
    remaining_revisions(schema)
    actual: dict[str, Any] = catalog(connection)  # type: ignore[no-untyped-call]
    expected_new = new_tables(backend, schema)
    all_new = new_tables(backend, CHAIN[-1])
    if all_new.intersection(actual) != expected_new:
        raise ValueError("unexpected_export_table_checkpoint")
    verify_manager_checkpoint(actual, schema)
    verify_source_projection(connection, actual, schema)
    for table, (name, columns) in SEEK_INDEXES.items():
        matching = [row for row in actual[table]["indexes"] if row[0] == name]
        definition = f"CREATEINDEX{name}ONpublic.{table}USINGbtree({columns})"
        if table == "traveller_reconciliation_jobs":
            definition += _ADVANCE_PREDICATE
        if schema == SOURCE or table == MANAGER_TABLE and schema != CHAIN[1]:
            if matching:
                raise ValueError("unexpected_export_index_checkpoint")
        elif (len(matching) != 1 or not all(matching[0][1:4])
                or _normalize_constraint(matching[0][-1]) != _normalize_constraint(definition)):
            raise ValueError("export_seek_index_not_ready")
    required_grants = _dml_grants(connection, "passport_submissions")
    quote = connection.dialect.identifier_preparer.quote_identifier
    for name in sorted(expected_new):
        table = actual[name]
        if any(not row[2] for row in table["constraints"]) or any(not all(row[1:4]) for row in table["indexes"]):
            raise ValueError("new_table_constraint_or_index_not_valid")
        if connection.execute(text(f"SELECT EXISTS (SELECT 1 FROM public.{quote(name)})")).scalar_one():
            raise ValueError("export_tables_must_be_empty_before_activation")
        if not required_grants <= _dml_grants(connection, name):
            raise ValueError("new_table_runtime_privileges_missing")
    return retained_catalog(actual, all_new)


def verify_source_projection(connection: Any, actual: dict[str, Any], schema: str) -> None:
    """The sole new historical field must equal its scoped original source date."""
    columns = [row for row in actual["traveller_match_cases"]["columns"] if row[0] == SOURCE_PROJECTION]
    if schema == SOURCE:
        if columns:
            raise ValueError("unexpected_source_projection_at_source")
        return
    if columns != [[SOURCE_PROJECTION, "timestamp with time zone", "YES", None, None, "NO", "NEVER"]]:
        raise ValueError("source_projection_shape_changed")
    mismatch = connection.scalar(text("""
        SELECT EXISTS (
          SELECT 1 FROM traveller_match_cases c
          LEFT JOIN passport_submissions s ON s.id = CASE
            WHEN c.source_kind = 'passport_submission'
              AND c.source_row_key ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
            THEN c.source_row_key::uuid ELSE NULL END
            AND s.agency_id = c.agency_id AND s.group_id = c.group_id
          WHERE c.source_created_at IS DISTINCT FROM s.created_at
        )
    """))
    if mismatch:
        raise ValueError("source_projection_backfill_changed")


def preservation_snapshot(connection: Any, backend: Path, schema: str) -> dict[str, Any]:
    retained = verify_schema(connection, backend, schema)
    return {"catalog": retained, "rows": authority_snapshot(connection, retained), "acl": _acl_snapshot(connection, retained)}
