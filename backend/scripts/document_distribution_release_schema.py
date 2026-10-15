"""Preserve every original row, table catalog and grant across 0138→0140.

Only the two reviewed nullable columns are normalized from the source digest.
They must remain null before activation. Row hashing streams 100 rows at a time;
the release helper bounds server statement time and sort memory.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from sqlalchemy import text

from scripts.document_distribution_release import CHAIN, SOURCE, remaining_revisions
from scripts.mcp_dashboard_write_schema import catalog
from scripts.release_travel_tracker_upgrade import _acl_snapshot

ADDITIONS = {
    "passport_submissions": (CHAIN[0], ["display_name", "character varying", "YES", 255, None, "NO", "NEVER"]),
    "whatsapp_message_logs": (CHAIN[1], ["document_update_context", "jsonb", "YES", None, None, "NO", "NEVER"]),
}


def retained_catalog(value: dict[str, Any]) -> dict[str, Any]:
    return {name: {**table, "columns": [row for row in table["columns"]
        if name not in ADDITIONS or row[0] != ADDITIONS[name][1][0]]}
        for name, table in value.items() if name != "alembic_version"}


def verify_schema(connection: Any, backend: Path, schema: str) -> dict[str, Any]:
    remaining_revisions(schema)
    actual: dict[str, Any] = catalog(connection)
    for table, (revision, expected) in ADDITIONS.items():
        if table not in actual:
            raise ValueError("required_document_table_missing")
        present = schema != SOURCE and CHAIN.index(schema) >= CHAIN.index(revision)
        columns = [row for row in actual[table]["columns"] if row[0] == expected[0]]
        if columns != ([expected] if present else []):
            raise ValueError("document_column_checkpoint_changed")
        if present:
            quote = connection.dialect.identifier_preparer.quote_identifier
            if connection.scalar(text(f"SELECT EXISTS (SELECT 1 FROM public.{quote(table)} WHERE {quote(expected[0])} IS NOT NULL)")):
                raise ValueError("new_document_columns_must_remain_null_before_activation")
    return retained_catalog(actual)


def authority_snapshot(connection: Any, tables: dict[str, Any]) -> dict[str, Any]:
    result = {}
    quote = connection.dialect.identifier_preparer.quote_identifier
    for name in sorted(tables):
        projection = "to_jsonb(record)"
        if name in ADDITIONS:
            projection += f" - '{ADDITIONS[name][1][0]}'"
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


def column_acl_snapshot(connection: Any, tables: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for name in sorted(tables):
        rows = connection.execute(text("""SELECT a.attname,a.attacl::text FROM pg_attribute a
            WHERE a.attrelid=to_regclass(:name) AND a.attnum>0 AND NOT a.attisdropped
            ORDER BY a.attname"""), {"name": "public." + name}).all()
        excluded = ADDITIONS[name][1][0] if name in ADDITIONS else None
        if any(row[0] == excluded and row[1] is not None for row in rows):
            raise ValueError("new_document_column_grants_forbidden")
        result[name] = [list(row) for row in rows if row[0] != excluded]
    return result


def preservation_snapshot(connection: Any, backend: Path, schema: str) -> dict[str, Any]:
    retained = verify_schema(connection, backend, schema)
    return {"catalog": retained, "rows": authority_snapshot(connection, retained),
        "acl": _acl_snapshot(connection, retained), "column_acl": column_acl_snapshot(connection, retained)}
