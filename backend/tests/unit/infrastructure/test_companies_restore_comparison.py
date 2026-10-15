"""Only the two observed PostgreSQL catalog deparse rewrites may vary."""

from copy import deepcopy

import pytest

from scripts import companies_restore_comparison as comparison
from scripts.release_companies_traveller_upgrade import preservation_digest

SOURCE = "(ARRAY['accepted'::charactervarying,'reconciled'::charactervarying,'overridden'::charactervarying])::text[]"
RESTORED = "ARRAY[('accepted'::charactervarying)::text,('reconciled'::charactervarying)::text,('overridden'::charactervarying)::text]"


def snapshot(expression=SOURCE):
    return {
        "catalog": {"legacy": {
            "relation": ["r", False, False, "p"],
            "columns": [["status", "character varying", "NO", 32, "'accepted'::character varying", "NO", "NEVER"]],
            "constraints": [["ck_status", "c", True, False, False,
                             f"CHECK(((status)::text=ANY({expression})))"]],
            "indexes": [["ix_status", True, True, True,
                         f"CREATEINDEXix_statusONpublic.legacyUSINGbtree(id)WHERE((status)::text=ANY({expression}))"]],
            "triggers": [["immutable", "O", "CREATETRIGGERimmutableBEFOREUPDATEONlegacyEXECUTEFUNCTIONguard()"]],
        }},
        "rows": {"legacy": {"count": 700, "sha256": "a" * 64}},
        "acl": {"legacy": ["qualification", "{qualification=arwdDxt/qualification,runtime=arwd/qualification}"]},
        "runtime_grants": [(12345, "SELECT", False)],
    }


def test_observed_restore_representation_is_accepted_without_changing_exact_baseline():
    before, restored = snapshot(), snapshot(RESTORED)
    original_before, original_restored = deepcopy(before), deepcopy(restored)
    assert comparison.restored_baseline(before, restored) is restored
    assert before == original_before and restored == original_restored
    assert preservation_digest(before) != preservation_digest(restored)
    assert preservation_digest(comparison.restored_baseline(before, restored)) == preservation_digest(restored)


@pytest.mark.parametrize("literal", ["''", "'O''Brien'", "'मंजूर'", "'ARRAY[''x''::charactervarying]'"])
def test_literal_bytes_and_quoted_apostrophes_are_preserved(literal):
    before = f"(ARRAY[{literal}::charactervarying])::text[]"
    after = f"ARRAY[({literal}::charactervarying)::text]"
    assert comparison.normalize_literal_array_casts(before) == after
    assert comparison.normalize_literal_array_casts(after) == after


@pytest.mark.parametrize("definition", [
    "(ARRAY['accepted'::charactervarying(4)])::text[]",
    "(ARRAY['accepted'::text])::text[]",
    "(ARRAY['accepted'::bpchar])::text[]",
    "(ARRAY[status::charactervarying])::text[]",
    "(ARRAY[NULL::charactervarying])::text[]",
    "(ARRAY[E'accepted'::charactervarying])::text[]",
    "(ARRAY['accepted'::charactervarying,'other'::text])::text[]",
    "(ARRAY['accepted'::charactervarying])::varchar[]",
    "(ARRAY['accepted'::charactervarying])::text[3]",
    "fn(ARRAY['accepted'::charactervarying])::text[]",
    '"fn"(ARRAY[\'accepted\'::charactervarying])::text[]',
    "'(ARRAY[''accepted''::charactervarying])::text[]'",
    '"(ARRAY[\'accepted\'::charactervarying])::text[]"',
])
def test_unreviewed_types_expressions_and_quoted_content_are_not_rewritten(definition):
    assert comparison.normalize_literal_array_casts(definition) == definition


@pytest.mark.parametrize("replacement", [
    RESTORED.replace("'accepted'", "'changed'"),
    RESTORED.replace("'accepted'", "'temporary'").replace("'reconciled'", "'accepted'").replace("'temporary'", "'reconciled'"),
    RESTORED.replace("charactervarying", "charactervarying(4)", 1),
    RESTORED.replace("charactervarying", "text", 1),
    RESTORED.replace("::text", "::bpchar", 1),
])
def test_changed_literals_order_or_types_are_rejected(replacement):
    with pytest.raises(AssertionError, match="Restored 0129"):
        comparison.restored_baseline(snapshot(), snapshot(replacement))


@pytest.mark.parametrize("section", ["rows", "acl", "runtime_grants", "columns", "triggers", "constraint_state", "index_state"])
def test_every_other_preservation_dimension_remains_exact(section):
    before, restored = snapshot(), snapshot(RESTORED)
    if section in {"rows", "acl", "runtime_grants"}:
        restored[section] = "changed"
    elif section in {"columns", "triggers"}:
        restored["catalog"]["legacy"][section][0][-1] = "changed"
    elif section == "constraint_state":
        restored["catalog"]["legacy"]["constraints"][0][2] = False
    else:
        restored["catalog"]["legacy"]["indexes"][0][1] = False
    with pytest.raises(AssertionError, match="Restored 0129"):
        comparison.restored_baseline(before, restored)


def test_multiple_array_casts_are_handled_without_reordering_surrounding_sql():
    value = f"CHECK((a=ANY({SOURCE}))AND(b=ANY({SOURCE})))"
    expected = f"CHECK((a=ANY({RESTORED}))AND(b=ANY({RESTORED})))"
    assert comparison.normalize_literal_array_casts(value) == expected


def test_definition_and_catalog_sizes_are_bounded(monkeypatch):
    with pytest.raises(ValueError, match="definition_size_limit"):
        comparison.normalize_literal_array_casts("x" * (comparison.MAX_DEFINITION_BYTES + 1))
    with pytest.raises(ValueError, match="unterminated_quote"):
        comparison.normalize_literal_array_casts("CHECK('unterminated)")
    monkeypatch.setattr(comparison, "MAX_CATALOG_DEFINITION_BYTES", 10)
    with pytest.raises(ValueError, match="catalog_definition_size_limit"):
        comparison.restored_baseline(snapshot(), snapshot())


TIMEZONE_SOURCE = "CHECK((((length((timezone)::text)>=1)AND(length((timezone)::text)<=64))AND((timezone)::text=TRIM(BOTHFROMtimezone))))"
TIMEZONE_RESTORED = "CHECK(((length((timezone)::text)>=1)AND(length((timezone)::text)<=64)AND((timezone)::text=TRIM(BOTHFROMtimezone))))"
DIMENSION_SOURCE = "CHECK((((width>=1)AND(width<=100000))AND((height>=1)AND(height<=100000))AND((byte_size>=1)AND(byte_size<=209715200))))"
DIMENSION_RESTORED = "CHECK(((width>=1)AND(width<=100000)AND((height>=1)AND(height<=100000))AND((byte_size>=1)AND(byte_size<=209715200))))"


def constraint_snapshot(definition):
    value = snapshot()
    value["catalog"]["legacy"]["constraints"][0][-1] = definition
    return value


@pytest.mark.parametrize("before,after", [
    (TIMEZONE_SOURCE, TIMEZONE_RESTORED),
    (DIMENSION_SOURCE, DIMENSION_RESTORED),
    ("CHECK(((timezoneISNULL)OR(((a)AND(b))AND(c))))",
     "CHECK(((timezoneISNULL)OR((a)AND(b)AND(c))))"),
    ("CHECK(((a)AND((b)AND((c)AND(d)))))", "CHECK(((a)AND(b)AND(c)AND(d)))"),
    ("CHECK((((a)AND(b))AND((c)AND(d))))", "CHECK(((a)AND(b)AND(c)AND(d)))"),
])
def test_observed_and_association_preserves_the_actual_restored_baseline(before, after):
    original, restored = constraint_snapshot(before), constraint_snapshot(after)
    saved_original, saved_restored = deepcopy(original), deepcopy(restored)
    assert comparison.normalize_associative_and(before) == comparison.normalize_associative_and(after)
    assert comparison.restored_baseline(original, restored) is restored
    assert original == saved_original and restored == saved_restored
    assert preservation_digest(original) != preservation_digest(restored)


@pytest.mark.parametrize("definition", [
    "CHECK(((a)AND(b))OR(c))",  # OR itself is never flattened.
    "CHECK(((a)OR(b))OR(c))",
    "CHECK((((a)AND(b))OR(c)AND(d)))",  # Mixed root stays entirely opaque.
    "CHECK(NOT(((a)AND(b))AND(c)))",
    "CHECK((NOT(((a)AND(b))AND(c))))",
    "CHECK((fn(((a)AND(b))AND(c)))AND(d))",
    'CHECK(("fn"(((a)AND(b))AND(c)))AND(d))',
    "CHECK((((a)AND(b))::boolean)AND(c))",
    'CHECK((((a)AND(b))COLLATE"x")AND(c))',
    "CHECK((((a)AND(b))+(c)))",
    "CHECK(((a+b)*c)>0)",
    "CHECK((aBETWEENbANDc)AND(d))",
    "CHECK((aANDb)AND(c))",  # Identifier is not the exact AND token.
    "CHECK(((a)and(b))AND(c))",
    "CHECK(((a)AND(b))AND(c))NOTVALID",  # Only a complete CHECK root.
    "fn(((a)AND(b))AND(c))",
    "CHECK(('((a)AND(b))AND(c)'='O''Brien'))",
    'CHECK(("((a)AND(b))AND(c)"=1))',
    "CHECK(((((a)))))",  # Redundant wrappers are not generally stripped.
])
def test_other_boolean_and_expression_structures_remain_byte_exact(definition):
    assert comparison.normalize_associative_and(definition) == definition


@pytest.mark.parametrize("after", [
    TIMEZONE_RESTORED.replace("<=64", "<=65"),
    TIMEZONE_RESTORED.replace(">=1", ">1"),
    TIMEZONE_RESTORED.replace("AND", "OR", 1),
    TIMEZONE_RESTORED.replace("length((timezone)::text)>=1", "length((timezone)::text)<=64", 1),
    "CHECK(((length((timezone)::text)<=64)AND(length((timezone)::text)>=1)AND((timezone)::text=TRIM(BOTHFROMtimezone))))",
    "CHECK(NOT((length((timezone)::text)>=1)AND(length((timezone)::text)<=64)AND((timezone)::text=TRIM(BOTHFROMtimezone))))",
])
def test_changed_threshold_operator_order_multiplicity_or_not_are_rejected(after):
    with pytest.raises(AssertionError, match="Restored 0129"):
        comparison.restored_baseline(constraint_snapshot(TIMEZONE_SOURCE), constraint_snapshot(after))


def test_opaque_leaves_keep_quotes_function_cast_collation_and_arithmetic_bytes():
    leaves = ["('AND(('='O''Brien')", '("AND(()"=1)', "(fn(a,b)>0)",
              "(((a+b)*c)>0)", '(value::textCOLLATE"C"=\'x\')', "(aBETWEENbANDc)"]
    before = "CHECK(((" + "AND".join(leaves[:3]) + ")AND(" + "AND".join(leaves[3:]) + ")))"
    after = "CHECK((" + "AND".join(leaves) + "))"
    assert comparison.normalize_associative_and(before) == after


def test_and_normalization_applies_only_to_constraint_definitions():
    before, after = snapshot(), snapshot()
    before["catalog"]["legacy"]["indexes"][0][-1] = TIMEZONE_SOURCE
    after["catalog"]["legacy"]["indexes"][0][-1] = TIMEZONE_RESTORED
    with pytest.raises(AssertionError, match="Restored 0129"):
        comparison.restored_baseline(before, after)


def test_deep_and_tree_is_iterative_bounded_and_preserves_duplicate_leaves():
    depth = 2000
    before = "CHECK(" + "(" * depth + "(a)" + "AND(b))" * depth + ")"
    after = "CHECK((" + "AND".join(["(a)"] + ["(b)"] * depth) + "))"
    assert comparison.normalize_associative_and(before) == after
    with pytest.raises(ValueError, match="definition_size_limit"):
        comparison.normalize_associative_and("x" * (comparison.MAX_DEFINITION_BYTES + 1))
    with pytest.raises(ValueError, match="unbalanced_parentheses"):
        comparison.normalize_associative_and("CHECK(((a)AND(b))")
