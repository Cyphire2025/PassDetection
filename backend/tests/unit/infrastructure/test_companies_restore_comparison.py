"""Only the observed PostgreSQL literal-array cast deparse may vary on restore."""

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
