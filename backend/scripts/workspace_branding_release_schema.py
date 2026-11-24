"""Preserve every original row, table catalog and grant across the reviewed 0140/0141 to 0142 chain.

Only columns introduced after the selected baseline are normalized from its digest.
They must remain null before activation. Row hashing streams 100 rows at a time;
the release helper bounds server statement time and sort memory.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import text

from scripts.mcp_dashboard_write_schema import catalog
from scripts.release_travel_tracker_upgrade import _acl_snapshot
from scripts.workspace_branding_release import CHAIN, SOURCE, remaining_revisions

ADDITIONS = {
    "client_organizations": (
        (CHAIN[0], ["logo_image_key", "character varying", "YES", 512, None, "NO", "NEVER"]),
    ),
    "client_groups": (
        (CHAIN[0], ["banner_image_key", "character varying", "YES", 512, None, "NO", "NEVER"]),
        (CHAIN[1], ["background_image_key", "character varying", "YES", 512, None, "NO", "NEVER"]),
    ),
}


def _checkpoint(schema: str) -> int:
    remaining_revisions(schema)
    return -1 if schema == SOURCE else CHAIN.index(schema)


def new_columns(table: str, baseline_schema: str) -> set[str]:
    baseline = _checkpoint(baseline_schema)
    return {column[0] for revision, column in ADDITIONS.get(table, ())
            if CHAIN.index(revision) > baseline}


def retained_catalog(value: dict[str, Any], baseline_schema: str = SOURCE) -> dict[str, Any]:
    return {name: {**table, "columns": [row for row in table["columns"]
        if row[0] not in new_columns(name, baseline_schema)]}
        for name, table in value.items() if name != "alembic_version"}


def verify_schema(connection: Any, backend: Path, schema: str,
                  baseline_schema: str = SOURCE) -> dict[str, Any]:
    checkpoint = _checkpoint(schema)
    if checkpoint < _checkpoint(baseline_schema):
        raise ValueError("source_schema_mismatch")
    actual: dict[str, Any] = catalog(connection)
    for table, additions in ADDITIONS.items():
        if table not in actual:
            raise ValueError("required_document_table_missing")
        for revision, expected in additions:
            present = checkpoint >= CHAIN.index(revision)
            columns = [row for row in actual[table]["columns"] if row[0] == expected[0]]
            if columns != ([expected] if present else []):
                raise ValueError("document_column_checkpoint_changed")
            if present and expected[0] in new_columns(table, baseline_schema):
                quote = connection.dialect.identifier_preparer.quote_identifier
                if connection.scalar(text(f"SELECT EXISTS (SELECT 1 FROM public.{quote(table)} WHERE {quote(expected[0])} IS NOT NULL)")):
                    raise ValueError("new_document_columns_must_remain_null_before_activation")
    return retained_catalog(actual, baseline_schema)


def authority_snapshot(connection: Any, tables: dict[str, Any],
                       baseline_schema: str = SOURCE) -> dict[str, Any]:
    result = {}
    quote = connection.dialect.identifier_preparer.quote_identifier
    for name in sorted(tables):
        projection = "to_jsonb(record)"
        for column in sorted(new_columns(name, baseline_schema)):
            projection += f" - '{column}'"
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


def column_acl_snapshot(connection: Any, tables: dict[str, Any],
                        baseline_schema: str = SOURCE) -> dict[str, Any]:
    result = {}
    for name in sorted(tables):
        rows = connection.execute(text("""SELECT a.attname,a.attacl::text FROM pg_attribute a
            WHERE a.attrelid=to_regclass(:name) AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY a.attname"""), {"name": "public." + name}).all()
        excluded = new_columns(name, baseline_schema)
        if any(row[0] in excluded and row[1] is not None for row in rows):
            raise ValueError("new_document_column_grants_forbidden")
        result[name] = [list(row) for row in rows if row[0] not in excluded]
    return result


def preservation_snapshot(connection: Any, backend: Path, schema: str,
                          baseline_schema: str = SOURCE) -> dict[str, Any]:
    retained = verify_schema(connection, backend, schema, baseline_schema)
    return {"catalog": retained, "rows": authority_snapshot(connection, retained, baseline_schema),
        "acl": _acl_snapshot(connection, retained),
        "column_acl": column_acl_snapshot(connection, retained, baseline_schema)}
