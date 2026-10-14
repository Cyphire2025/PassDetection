"""Fenced 0135→0138 proof: preserve every existing row, catalog item and ACL.

Only eight new empty tables, one nullable keyed projection, its exact index and
two actor-label CHECK expansions are normalized. Existing queue rows, images,
source chronology and identity ownership remain in the preservation digest.
Hashing is O(R log R) server sort work / O(100 rows) client memory; maintenance
only, with a 120-second statement limit and 16 MiB work_mem.
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

from sqlalchemy import text

from scripts.companies_restore_comparison import normalize_literal_array_casts
from scripts.companies_traveller_reuse_release import CHAIN, SOURCE, TARGET, remaining_revisions
from scripts.mcp_dashboard_write_schema import catalog
from scripts.release_travel_tracker_upgrade import _acl_snapshot, _dml_grants

NEW_BY_REVISION = {
    CHAIN[0]: frozenset({'traveller_returning_drafts', 'traveller_draft_assets', 'traveller_draft_contact_proofs'}),
    CHAIN[1]: frozenset({'company_directory_states', 'company_directory_people', 'company_directory_prefixes',
        'company_directory_group_counts', 'company_directory_queue'}),
    CHAIN[2]: frozenset(),
}
ACTOR_CONSTRAINTS = {'traveller_claims': 'ck_traveller_claim_actor', 'traveller_history_grants': 'ck_traveller_grant_actor'}
LOOKUP_COLUMN = 'number_lookup_fingerprint'
LOOKUP_INDEX = 'ix_traveller_passport_number_lookup'


def _declared_tables(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_bytes())):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'DDL' for target in node.targets):
            for statement in ast.literal_eval(node.value):
                match = re.match(r'CREATE TABLE ([a-z_]+)\s*\(', statement)
                if match:
                    names.add(match[1])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'create_table':
            names.add(ast.literal_eval(node.args[0]))
    return names


def new_tables(backend: Path, schema: str) -> set[str]:
    remaining_revisions(schema)
    names: set[str] = set()
    for revision in CHAIN:
        declared = _declared_tables(backend / 'alembic/versions' / f'{revision}.py')
        if declared != NEW_BY_REVISION[revision]:
            raise ValueError('exact_portal_projection_tables_required')
        if schema != SOURCE and CHAIN.index(revision) <= CHAIN.index(schema):
            names.update(declared)
    return names


def retained_catalog(value: dict[str, Any], all_new_tables: set[str]) -> dict[str, Any]:
    """Validate exact differences first; keep all unrelated schema in the digest."""
    return {name: {**table,
        'columns': [row for row in table['columns'] if not (name == 'traveller_passports' and row[0] == LOOKUP_COLUMN)],
        'indexes': [row for row in table['indexes'] if not (name == 'traveller_passports' and row[0] == LOOKUP_INDEX)],
        'constraints': [row for row in table['constraints'] if row[0] != ACTOR_CONSTRAINTS.get(name)],
    } for name, table in value.items() if name not in all_new_tables and name != 'alembic_version'}


def authority_snapshot(connection: Any, tables: dict[str, Any]) -> dict[str, Any]:
    result = {}
    quote = connection.dialect.identifier_preparer.quote_identifier
    for name in sorted(tables):
        projection = 'to_jsonb(record)' + (f" - '{LOOKUP_COLUMN}'" if name == 'traveller_passports' else '')
        rows = connection.execute(text(
            f'SELECT ({projection})::text AS original FROM public.{quote(name)} record ORDER BY original'
        ).execution_options(stream_results=True, yield_per=100))
        digest, count = hashlib.sha256(), 0
        try:
            for row in rows:
                digest.update(row[0].encode('utf-8'))
                digest.update(b'\n')
                count += 1
        finally:
            rows.close()
        result[name] = {'count': count, 'sha256': digest.hexdigest()}
    return result


def _normalize(value: str) -> str:
    return re.sub(r'[\s()]', '', normalize_literal_array_casts(value))


def verify_actor_checkpoint(actual: dict[str, Any], schema: str) -> None:
    values = ('self', 'delegate', 'guardian', 'verified') if schema == TARGET else ('self', 'delegate', 'guardian')
    labels = ','.join(f"'{value}'::charactervarying" for value in values)
    expected = f'CHECK(actor_kind::text=ANY((ARRAY[{labels}])::text[]))'
    for table, name in ACTOR_CONSTRAINTS.items():
        rows = [row for row in actual[table]['constraints'] if row[0] == name]
        if len(rows) != 1 or rows[0][1:5] != ['c', True, False, False] or _normalize(rows[0][-1]) != _normalize(expected):
            raise ValueError('actor_constraint_checkpoint_changed')


def verify_lookup_checkpoint(connection: Any, actual: dict[str, Any], schema: str) -> None:
    columns = [row for row in actual['traveller_passports']['columns'] if row[0] == LOOKUP_COLUMN]
    indexes = [row for row in actual['traveller_passports']['indexes'] if row[0] == LOOKUP_INDEX]
    if schema != TARGET:
        if columns or indexes:
            raise ValueError('unexpected_lookup_before_target')
        return
    if columns != [[LOOKUP_COLUMN, 'character varying', 'YES', 64, None, 'NO', 'NEVER']]:
        raise ValueError('lookup_projection_shape_changed')
    expected = f'CREATE INDEX {LOOKUP_INDEX} ON public.traveller_passports USING btree (agency_id, company_id, fingerprint_key_version, {LOOKUP_COLUMN})'
    if len(indexes) != 1 or indexes[0][1:4] != [True, True, True] or _normalize(indexes[0][-1]) != _normalize(expected):
        raise ValueError('lookup_index_checkpoint_changed')
    if connection.scalar(text(f'SELECT EXISTS (SELECT 1 FROM traveller_passports WHERE {LOOKUP_COLUMN} IS NOT NULL)')):
        raise ValueError('lookup_backfill_must_wait_for_activation')


def verify_schema(connection: Any, backend: Path, schema: str) -> dict[str, Any]:
    remaining_revisions(schema)
    actual: dict[str, Any] = catalog(connection)  # type: ignore[no-untyped-call]
    expected_new, all_new = new_tables(backend, schema), new_tables(backend, TARGET)
    if all_new.intersection(actual) != expected_new:
        raise ValueError('unexpected_portal_table_checkpoint')
    verify_actor_checkpoint(actual, schema)
    verify_lookup_checkpoint(connection, actual, schema)
    required_grants = _dml_grants(connection, 'passport_submissions')
    quote = connection.dialect.identifier_preparer.quote_identifier
    for name in sorted(expected_new):
        table = actual[name]
        if any(not row[2] for row in table['constraints']) or any(not all(row[1:4]) for row in table['indexes']):
            raise ValueError('new_table_constraint_or_index_not_valid')
        if connection.execute(text(f'SELECT EXISTS (SELECT 1 FROM public.{quote(name)})')).scalar_one():
            raise ValueError('new_tables_must_be_empty_before_activation')
        if not required_grants <= _dml_grants(connection, name):
            raise ValueError('new_table_runtime_privileges_missing')
    return retained_catalog(actual, all_new)


def preservation_snapshot(connection: Any, backend: Path, schema: str) -> dict[str, Any]:
    retained = verify_schema(connection, backend, schema)
    return {'catalog': retained, 'rows': authority_snapshot(connection, retained), 'acl': _acl_snapshot(connection, retained)}
