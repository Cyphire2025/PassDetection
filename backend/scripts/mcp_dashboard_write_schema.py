"""Pure catalog/retention checks used by the qualified additive migration helper."""

import hashlib
import re

from sqlalchemy import text

SOURCE = "0125_mcp_connection_requests"
TARGET = "0128_mcp_document_delivery"
NEW_TABLES = frozenset(
    {"mcp_native_transfers", "mcp_document_delivery_plans", "mcp_document_delivery_outbox"}
)
NEW_COLUMNS = {
    "mcp_control": frozenset(
        {"read_enabled", "write_enabled", "allowed_write_sections", "allowed_write_tools"}
    ),
    "mcp_grants": frozenset(
        {
            "read_enabled",
            "write_enabled",
            "allowed_write_sections",
            "allowed_read_sections",
            "permission_revision",
        }
    ),
    "mcp_connection_requests": frozenset(
        {"read_enabled", "write_enabled", "allowed_write_sections", "allowed_read_sections"}
    ),
}


def canonical(value):
    return re.sub(
        r"'(?:[^']|'')*'|\s+", lambda match: match[0] if match[0].startswith("'") else "", value
    )


def catalog(connection):
    tables = connection.execute(
        text("""SELECT c.relname,c.relkind::text,c.relrowsecurity,c.relforcerowsecurity,c.relpersistence::text
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p') ORDER BY c.relname""")
    ).all()
    if len(tables) > 512:
        raise ValueError("public_table_budget_exceeded")
    result = {}
    for name, *relation in tables:
        columns = connection.execute(
            text("""SELECT column_name,data_type,is_nullable,character_maximum_length,
            column_default,is_identity,is_generated FROM information_schema.columns
            WHERE table_schema='public' AND table_name=:name ORDER BY column_name"""),
            {"name": name},
        ).all()
        constraints = connection.execute(
            text("""SELECT conname,contype::text,convalidated,condeferrable,condeferred,pg_get_constraintdef(oid)
            FROM pg_constraint WHERE conrelid=to_regclass(:relation) ORDER BY conname"""),
            {"relation": "public." + name},
        ).all()
        indexes = connection.execute(
            text("""SELECT c.relname,i.indisvalid,i.indisready,i.indislive,pg_get_indexdef(i.indexrelid)
            FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
            WHERE i.indrelid=to_regclass(:relation) ORDER BY c.relname"""),
            {"relation": "public." + name},
        ).all()
        triggers = connection.execute(
            text("""SELECT tgname,tgenabled::text,pg_get_triggerdef(oid) FROM pg_trigger
            WHERE tgrelid=to_regclass(:relation) AND NOT tgisinternal ORDER BY tgname"""),
            {"relation": "public." + name},
        ).all()
        result[name] = {
            "relation": relation,
            "columns": [list(row) for row in columns],
            "constraints": [list(row[:-1]) + [canonical(row[-1])] for row in constraints],
            "indexes": [list(row[:-1]) + [canonical(row[-1])] for row in indexes],
            "triggers": [list(row[:-1]) + [canonical(row[-1])] for row in triggers],
        }
    return result


def target_profile(value):
    return {
        "version": 1,
        "schema": TARGET,
        "new_tables": {name: value[name] for name in sorted(NEW_TABLES)},
        "permissions": {
            name: {
                "columns": [row for row in value[name]["columns"] if row[0] in columns],
                "constraints": [
                    row
                    for row in value[name]["constraints"]
                    if row[0] == "ck_mcp_grant_permission_revision"
                ],
            }
            for name, columns in NEW_COLUMNS.items()
        },
    }


def verify_schema(connection, schema, profile):
    actual = catalog(connection)
    if schema == SOURCE:
        if NEW_TABLES & actual.keys() or any(
            any(row[0] in columns for row in actual[name]["columns"])
            for name, columns in NEW_COLUMNS.items()
        ):
            raise ValueError("source_schema_has_unreviewed_additions")
        return actual
    if schema != TARGET or not NEW_TABLES <= actual.keys() or target_profile(actual) != profile:
        raise ValueError("target_schema_profile_mismatch")
    for name in NEW_TABLES:
        if connection.execute(text(f'SELECT EXISTS (SELECT 1 FROM public."{name}")')).scalar_one():
            raise ValueError("new_tables_must_be_empty_before_activation")
    for name in NEW_COLUMNS:
        clauses = (
            "read_enabled IS TRUE AND write_enabled IS FALSE AND allowed_write_sections='[]'::jsonb"
        )
        if name == "mcp_control":
            clauses += " AND allowed_write_tools='[]'::jsonb"
        else:
            clauses += " AND allowed_read_sections IS NULL"
        if name == "mcp_grants":
            clauses += " AND permission_revision=1"
        if connection.execute(
            text(f'SELECT EXISTS (SELECT 1 FROM public."{name}" WHERE NOT ({clauses}))')
        ).scalar_one():
            raise ValueError("new_permission_authority_must_remain_default_denied")
    return actual


def retained_catalog(value):
    result = {}
    for name, table in value.items():
        if name in NEW_TABLES or name == "alembic_version":
            continue
        result[name] = {
            **table,
            "columns": [row for row in table["columns"] if row[0] not in NEW_COLUMNS.get(name, ())],
            "constraints": [
                row for row in table["constraints"]
                if not (name == "mcp_grants" and row[0] == "ck_mcp_grant_permission_revision")
            ],
        }
    return result


def authority_snapshot(connection, tables=None):
    """Hash every old field, including timestamps; the executor fences all writers."""
    names = tables or retained_catalog(catalog(connection)).keys()
    result = {}
    quote = connection.dialect.identifier_preparer.quote_identifier
    for name in sorted(names):
        if name in NEW_TABLES or name == "alembic_version":
            continue
        excluded = sorted(NEW_COLUMNS.get(name, ()))
        projection = "to_jsonb(record)" + (" - CAST(:excluded AS text[])" if excluded else "")
        statement = text(
            f"SELECT ({projection})::text AS original FROM public.{quote(name)} record ORDER BY original"
        )
        rows = connection.execute(
            statement.execution_options(stream_results=True, yield_per=100),
            {"excluded": excluded} if excluded else {},
        )
        digest, count = hashlib.sha256(), 0
        try:
            for row in rows:
                digest.update(row[0].encode())
                digest.update(b"\n")
                count += 1
        finally:
            rows.close()
        result[name] = {"count": count, "sha256": digest.hexdigest()}
    return result
