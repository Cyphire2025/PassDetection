"""Bounded-memory preservation checks for the fenced Full-release window.

Historical hashing is O(R log R) database sort work and O(100 rows) client memory;
it is maintenance-only, with a 120-second statement limit and 16 MiB work_mem.
It never runs on an interactive request. Large installations must rehearse this
budget against their own backup before qualification, not extend it silently.
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

NEW_COLUMNS = {
    "client_organizations": {"revision"},
    "client_groups": {"company_id", "company_revision"},
}
NEW_CONSTRAINTS = {
    "client_groups": {"fk_client_groups_company_scope", "uq_client_groups_company_scope"},
    "gc_group_access": {"fk_gc_group_canonical_company"},
}
SOURCE_SEEK_INDEXES = {
    "passport_submissions": ("ix_passport_submissions_scoped_seek", "agency_id,group_id,id"),
    "whatsapp_broadcast_recipients": ("ix_whatsapp_recipient_source_seek", "broadcast_group_id,id"),
    "whatsapp_broadcast_rejected_contacts": ("ix_whatsapp_rejected_source_seek", "broadcast_group_id,id"),
}
NEW_INDEXES = {
    "client_groups": {"uq_client_groups_company_scope", "ix_client_groups_company_seek", "ix_client_groups_company_lifecycle"},
    "client_organizations": {"ix_client_org_directory_seek", "ix_client_org_directory_all_seek", "ix_client_org_search_trgm"},
    **{table: {name} for table, (name, _) in SOURCE_SEEK_INDEXES.items()},
}


def new_tables(backend: Path, schema: str) -> set[str]:
    """Read names from hash-bound frozen DDL without importing application models."""
    remaining_revisions(schema)
    stage = -1 if schema == SOURCE else CHAIN.index(schema)
    names = set()
    for index in (1, 3):
        if stage < index:
            continue
        source = backend / "alembic/versions" / f"{CHAIN[index]}.py"
        for node in ast.parse(source.read_bytes()).body:
            if isinstance(node, ast.Assign) and any(isinstance(name, ast.Name) and name.id == "DDL" for name in node.targets):
                for statement in ast.literal_eval(node.value):
                    matched = re.match(r"CREATE TABLE ([a-z_]+)\s*\(", statement)
                    if matched:
                        names.add(matched[1])
    return names


def retained_catalog(value: dict[str, Any], all_new_tables: set[str]) -> dict[str, Any]:
    return {
        name: {
            **table,
            "columns": [row for row in table["columns"] if row[0] not in NEW_COLUMNS.get(name, ())],
            "constraints": [row for row in table["constraints"] if row[0] not in NEW_CONSTRAINTS.get(name, ())],
            "indexes": [row for row in table["indexes"] if row[0] not in NEW_INDEXES.get(name, ())],
        }
        for name, table in value.items()
        if name not in all_new_tables and name != "alembic_version"
    }


def authority_snapshot(connection: Any, tables: dict[str, Any]) -> dict[str, Any]:
    result = {}
    quote = connection.dialect.identifier_preparer.quote_identifier
    for name in sorted(tables):
        excluded = sorted(NEW_COLUMNS.get(name, ()))
        projection = "to_jsonb(record)" + (" - CAST(:excluded AS text[])" if excluded else "")
        rows = connection.execute(text(
            f"SELECT ({projection})::text AS original FROM public.{quote(name)} record ORDER BY original"
        ).execution_options(stream_results=True, yield_per=100), {"excluded": excluded} if excluded else {})
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


def _verify_company_backfill(connection: Any) -> None:
    invalid = connection.execute(text("""
        SELECT EXISTS (
            SELECT 1 FROM client_groups g LEFT JOIN gc_group_access a
              ON a.group_id = g.id AND a.agency_id = g.agency_id
            WHERE g.company_id IS DISTINCT FROM a.client_organization_id
               OR g.company_revision <> CASE WHEN a.client_organization_id IS NULL THEN 0 ELSE 1 END
        ) OR EXISTS (SELECT 1 FROM client_organizations WHERE revision <> 1)
    """)).scalar_one()
    if invalid:
        raise ValueError("company_backfill_does_not_match_original_gc_scope")


def verify_schema(connection: Any, backend: Path, schema: str) -> dict[str, Any]:
    remaining_revisions(schema)
    actual: dict[str, Any] = catalog(connection)  # type: ignore[no-untyped-call]
    expected_new = new_tables(backend, schema)
    all_new = new_tables(backend, CHAIN[-1])
    if all_new.intersection(actual) != expected_new:
        raise ValueError("unexpected_reuse_table_checkpoint")
    for name, columns in NEW_COLUMNS.items():
        present = {row[0] for row in actual[name]["columns"]} & columns
        if present != (set() if schema == SOURCE else columns):
            raise ValueError("unexpected_company_column_checkpoint")
    for name, constraints in NEW_CONSTRAINTS.items():
        present = {row[0] for row in actual[name]["constraints"]} & constraints
        if present != (set() if schema == SOURCE else constraints):
            raise ValueError("unexpected_company_constraint_checkpoint")
    for name, indexes in NEW_INDEXES.items():
        if name in SOURCE_SEEK_INDEXES:
            continue  # An interrupted 0132 may leave an invalid index at 0131.
        present = {row[0] for row in actual[name]["indexes"]} & indexes
        if present != (set() if schema == SOURCE else indexes):
            raise ValueError("unexpected_company_index_checkpoint")
    if schema != SOURCE:
        _verify_company_backfill(connection)
    for table, (name, columns) in SOURCE_SEEK_INDEXES.items():
        matching = [row for row in actual[table]["indexes"] if row[0] == name]
        if schema in CHAIN[2:]:
            if len(matching) != 1 or not all(matching[0][1:4]) or f"USINGbtree({columns})" not in matching[0][-1]:
                raise ValueError("source_seek_index_not_ready")
        elif schema != CHAIN[1] and matching:
            raise ValueError("unexpected_source_seek_index_checkpoint")
    required_grants = _dml_grants(connection, "passport_submissions")
    quote = connection.dialect.identifier_preparer.quote_identifier
    for name in sorted(expected_new):
        table = actual[name]
        if any(not row[2] for row in table["constraints"]) or any(not all(row[1:4]) for row in table["indexes"]):
            raise ValueError("new_table_constraint_or_index_not_valid")
        if connection.execute(text(f"SELECT EXISTS (SELECT 1 FROM public.{quote(name)})")).scalar_one():
            raise ValueError("reuse_tables_must_be_empty_before_activation")
        if not required_grants <= _dml_grants(connection, name):
            raise ValueError("new_table_runtime_privileges_missing")
    return retained_catalog(actual, all_new)


def preservation_snapshot(connection: Any, backend: Path, schema: str) -> dict[str, Any]:
    retained = verify_schema(connection, backend, schema)
    return {"catalog": retained, "rows": authority_snapshot(connection, retained), "acl": _acl_snapshot(connection, retained)}
