"""Only the exact additive portal projection is excluded from preservation."""
import copy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import companies_traveller_release_schema as schema
from scripts.companies_traveller_reuse_release import CHAIN, SOURCE, TARGET


def actors(target=False, restored=False):
    values = ('self', 'delegate', 'guardian', 'verified') if target else ('self', 'delegate', 'guardian')
    labels = ','.join(f"'{value}'::charactervarying" for value in values)
    expression = f'CHECK(((actor_kind)::text=ANY((ARRAY[{labels}])::text[])))'
    if restored:
        expression = schema.normalize_literal_array_casts(expression)
    return {table: {'columns': [], 'indexes': [], 'triggers': [], 'relation': ['r', False, False, 'p'],
        'constraints': [[name, 'c', True, False, False, expression]]}
        for table, name in schema.ACTOR_CONSTRAINTS.items()}


@pytest.mark.parametrize('restored', [False, True])
def test_actor_expansion_only_at_final_checkpoint_and_never_relabels_rows(restored):
    old, new = actors(restored=restored), actors(True, restored)
    for checkpoint in (SOURCE, *CHAIN[:-1]):
        schema.verify_actor_checkpoint(old, checkpoint)
        with pytest.raises(ValueError):
            schema.verify_actor_checkpoint(new, checkpoint)
    schema.verify_actor_checkpoint(new, TARGET)
    with pytest.raises(ValueError):
        schema.verify_actor_checkpoint(old, TARGET)
    assert schema.retained_catalog(old, set()) == schema.retained_catalog(new, set())


@pytest.mark.parametrize('change', ['drop', 'unvalidated', 'deferrable', 'weaker', 'label', 'column'])
def test_actor_expansion_rejects_weakened_or_unrelated_definition(change):
    value = actors(True)
    rows = value['traveller_claims']['constraints']
    if change == 'drop':
        rows.clear()
    elif change == 'unvalidated':
        rows[0][2] = False
    elif change == 'deferrable':
        rows[0][3] = True
    elif change == 'weaker':
        rows[0][-1] += 'ORtrue'
    elif change == 'label':
        rows[0][-1] = rows[0][-1].replace('verified', 'trusted')
    else:
        rows[0][-1] = rows[0][-1].replace('actor_kind', 'status')
    with pytest.raises(ValueError, match='actor_constraint'):
        schema.verify_actor_checkpoint(value, TARGET)


def test_all_retained_chronology_manager_constraints_and_queue_fields_remain_hashed():
    original = {'traveller_match_cases': {'columns': [['source_created_at', 'timestamp']],
        'constraints': [['retained_scope', 'f', True]], 'indexes': [['retained_seek']], 'triggers': []}}
    assert schema.retained_catalog(original, set()) == original
    changed = copy.deepcopy(original)
    changed['traveller_match_cases']['columns'][0][1] = 'text'
    assert schema.retained_catalog(original, set()) != schema.retained_catalog(changed, set())
    connection, rows = MagicMock(), MagicMock()
    connection.dialect.identifier_preparer.quote_identifier.side_effect = lambda name: f'"{name}"'
    rows.__iter__.return_value = iter([('{"source_created_at":"original","actor_kind":"self"}',)])
    connection.execute.return_value = rows
    result = schema.authority_snapshot(connection, original)
    statement = connection.execute.call_args.args[0]
    assert "to_jsonb(record))::text" in str(statement)
    assert 'source_created_at' not in str(statement)  # No field exclusion.
    assert statement.get_execution_options()['yield_per'] == 100
    assert result['traveller_match_cases']['count'] == 1
    rows.close.assert_called_once()


def test_exact_new_tables_are_empty_additions_at_their_checkpoint():
    backend = Path(__file__).resolve().parents[3]
    assert schema.new_tables(backend, SOURCE) == set()
    assert schema.new_tables(backend, CHAIN[0]) == schema.NEW_BY_REVISION[CHAIN[0]]
    assert schema.new_tables(backend, CHAIN[1]) == set().union(*schema.NEW_BY_REVISION.values())
    assert len(schema.new_tables(backend, TARGET)) == 8


def test_nullable_lookup_has_exact_index_and_is_not_backfilled_during_ddl():
    actual = {'traveller_passports': {'columns': [], 'indexes': [], 'constraints': []}}
    connection = MagicMock()
    schema.verify_lookup_checkpoint(connection, actual, SOURCE)
    actual['traveller_passports']['columns'] = [[schema.LOOKUP_COLUMN, 'character varying', 'YES', 64, None, 'NO', 'NEVER']]
    actual['traveller_passports']['indexes'] = [[schema.LOOKUP_INDEX, True, True, True,
        f'CREATE INDEX {schema.LOOKUP_INDEX} ON public.traveller_passports USING btree (agency_id, company_id, fingerprint_key_version, {schema.LOOKUP_COLUMN})']]
    connection.scalar.return_value = False
    schema.verify_lookup_checkpoint(connection, actual, TARGET)
    assert schema.retained_catalog(actual, set())['traveller_passports']['columns'] == []
    for checkpoint in (SOURCE, *CHAIN[:-1]):
        with pytest.raises(ValueError, match='before_target'):
            schema.verify_lookup_checkpoint(connection, actual, checkpoint)
    connection.scalar.return_value = True
    with pytest.raises(ValueError, match='backfill'):
        schema.verify_lookup_checkpoint(connection, actual, TARGET)
    connection.scalar.return_value = False
    actual['traveller_passports']['indexes'][0][-1] += ' WHERE true'
    with pytest.raises(ValueError, match='index_checkpoint'):
        schema.verify_lookup_checkpoint(connection, actual, TARGET)
