"""Source/proof/config gates must reject before any database work."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import runpy
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[3]
ROOT = BACKEND.parent


def load_helper():
    spec = importlib.util.spec_from_file_location(
        "admin_approval_upgrade_unit", BACKEND / "scripts/apply_mcp_admin_approval_upgrade.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract():
    # This helper qualifies the frozen 0124→0125 contract, independently of the
    # current deployment manifest. Its migration bytes remain immutable.
    module = runpy.run_path(str(ROOT / "scripts/release_mcp_admin_approval_contract.py"))
    relative = module["PATH"]
    return {**copy.deepcopy(module["POLICY"]), "migrations": [{
        "revision": module["TARGET"], "parent": module["SOURCE"], "path": relative,
        "sha256": hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(),
    }]}


def test_exact_source_contract_is_accepted():
    load_helper().verify_sources(BACKEND, contract())


@pytest.mark.parametrize("field,value", [
    ("version", True),
    ("kind", "mcp_read_only_v1"),
    ("source_schema", "0122_mcp_gc_push"),
    ("target_schema", "0124_mcp_device_access"),
    ("read_only_mode", False),
    ("allowed_capabilities", ["mcp:read", "mcp:export"]),
    ("control_enabled", True),
    ("existing_grants", "expand"),
    ("read_section_authority", "reset"),
    ("connection_enabled", "reset"),
    ("pending_requests", "retain_any"),
    ("automatic_downgrade", True),
    ("migrations", []),
    ("arbitrary_command", "ignored"),
])
def test_other_policy_or_ancestry_is_rejected(field, value):
    changed = {**copy.deepcopy(contract()), field: value}
    with pytest.raises(ValueError):
        load_helper().verify_sources(BACKEND, changed)


@pytest.mark.parametrize("field,value", [
    ("sha256", "0" * 64), ("sha256", "A" * 64),
    ("path", "../../arbitrary.py"), ("parent", "0122_mcp_gc_push"),
    ("revision", "0124_mcp_device_access"), ("extra", "arbitrary"),
])
def test_migration_hash_identity_and_path_are_strict(field, value):
    changed = copy.deepcopy(contract())
    changed["migrations"][0][field] = value
    with pytest.raises(ValueError):
        load_helper().verify_sources(BACKEND, changed)


def test_missing_file_and_duplicate_identity_rejected(tmp_path):
    helper, value = load_helper(), contract()
    with pytest.raises(ValueError, match="invalid_migration_source"):
        helper.verify_sources(tmp_path, value)
    path = tmp_path / "alembic/versions/0125_mcp_connection_requests.py"
    path.parent.mkdir(parents=True)
    shutil.copyfile(BACKEND / "alembic/versions/0125_mcp_connection_requests.py", path)
    path.write_text(path.read_text("utf-8") + '\ndown_revision = "0124_mcp_device_access"\n',
                    encoding="utf-8")
    value["migrations"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="ambiguous_migration_identity"):
        helper.verify_sources(tmp_path, value)


@pytest.mark.parametrize("proof", [None, "", "0" * 63, "Z" * 64])
def test_release_proof_is_required_before_database_access(monkeypatch, proof):
    if proof is None:
        monkeypatch.delenv("MCP_RELEASE_PROOF_SHA256", raising=False)
    else:
        monkeypatch.setenv("MCP_RELEASE_PROOF_SHA256", proof)
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *args, **kwargs: pytest.fail(
        "Invalid proof reached database access"
    ))
    with pytest.raises(ValueError, match="release_proof_required"):
        load_helper().apply_upgrade(contract())


def test_write_capability_configuration_is_rejected_before_database_access(
    monkeypatch, test_settings
):
    from app.core.config.mcp import MCPSettings

    monkeypatch.setenv("MCP_RELEASE_PROOF_SHA256", "a" * 64)
    monkeypatch.setattr("app.core.config.settings.get_settings", lambda: test_settings.model_copy(
        update={"mcp": MCPSettings(_env_file=None, read_only_mode=False)}
    ))
    monkeypatch.setattr("sqlalchemy.create_engine", lambda *args, **kwargs: pytest.fail(
        "Write configuration reached database access"
    ))
    with pytest.raises(ValueError, match="read_only_deployment_required"):
        load_helper().apply_upgrade(contract())


def test_cli_failure_is_sanitized_and_forward_only(monkeypatch, capsys):
    helper = load_helper()
    monkeypatch.setattr(sys, "argv", ["upgrade", "--contract-json", json.dumps(contract())])

    def private_failure(_contract):
        raise RuntimeError("secret database URL credential and private record")

    monkeypatch.setattr(helper, "apply_upgrade", private_failure)
    assert helper.main() == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "status": "failed", "reason": "admin_approval_upgrade_failed",
        "automatic_downgrade": False,
    }
    assert "secret" not in output and "private" not in output


VALID_PLATFORM_CHECK = (
    "CHECK (((device_platform IS NULL) OR ((device_platform)::text = ANY "
    "((ARRAY['Windows'::character varying, 'macOS'::character varying, "
    "'Other'::character varying])::text[]))))"
)


def test_generated_platform_check_and_harmless_text_casts_are_accepted():
    helper = load_helper()
    assert helper._valid_platform_constraint(VALID_PLATFORM_CHECK)
    assert helper._valid_platform_constraint(
        VALID_PLATFORM_CHECK.replace("character varying", "text")
    )


@pytest.mark.parametrize("definition", [
    "CHECK (TRUE)",
    VALID_PLATFORM_CHECK.replace("'macOS'", "'Linux'"),
    VALID_PLATFORM_CHECK.replace("'Windows'", "'Win dows'"),
    VALID_PLATFORM_CHECK.replace("'Windows'", "'Win(dows)'"),
    VALID_PLATFORM_CHECK.replace(" OR ", " AND "),
    VALID_PLATFORM_CHECK.replace("device_platform", "name"),
    VALID_PLATFORM_CHECK[:-1] + " OR true)",
    VALID_PLATFORM_CHECK[:-1] + " AND false)",
    VALID_PLATFORM_CHECK.replace("'Other'::character varying", "'Other'::character varying, 'Linux'::text"),
    None,
])
def test_same_named_validated_check_with_wrong_predicate_is_rejected(definition):
    helper = load_helper()
    results = iter([
        SimpleNamespace(all=lambda: [
            ("device_platform", "character varying", "YES", None, 16),
            ("enabled", "boolean", "NO", "true", None),
        ]),
        SimpleNamespace(one_or_none=lambda: (True, definition)),
    ])
    connection = SimpleNamespace(execute=lambda _statement: next(results))
    with pytest.raises(ValueError, match="target_platform_constraint_mismatch"):
        helper._verify_columns(connection, helper.SOURCE)


def request_catalog(helper):
    return [
        ("r", False, False, "p"),
        [(name, *value, None, "NO", "NEVER")
         for name, value in sorted(helper.REQUEST_COLUMNS.items())],
        [(name, kind, True, False, False, definition)
         for name, (kind, definition) in sorted(helper.REQUEST_CONSTRAINTS.items())],
        [(name, True, True, True,
          f"CREATE {'UNIQUE ' if unique else ''}INDEX {name} ON "
          f"public.mcp_connection_requests USING btree ({columns})")
         for name, (unique, columns) in sorted(helper.REQUEST_INDEXES.items())],
        False,
    ]


def fake_connection(values):
    results = iter(values)

    def execute(_statement):
        value = next(results)
        return SimpleNamespace(all=lambda: value, one_or_none=lambda: value,
                               scalar_one=lambda: value)

    return SimpleNamespace(execute=execute)


def test_schema_qualification_is_separate_from_empty_activation_gate():
    helper = load_helper()
    helper._verify_request_schema(fake_connection(request_catalog(helper)), helper.TARGET)
    helper._require_empty_requests(fake_connection([False]))
    with pytest.raises(ValueError, match="pending_requests_must_be_empty"):
        helper._require_empty_requests(fake_connection([True]))


def test_source_refuses_an_existing_request_relation_and_unknown_schema():
    helper = load_helper()
    helper._verify_request_schema(fake_connection([None]), helper.SOURCE)
    with pytest.raises(ValueError, match="source_request_table_must_be_absent"):
        helper._verify_request_schema(fake_connection([("r", False, False, "p")]), helper.SOURCE)
    with pytest.raises(ValueError, match="source_schema_mismatch"):
        helper._verify_request_schema(fake_connection([]), "0123_mcp_read_sections")


@pytest.mark.parametrize("relation", [None, ("v", False, False, "p"),
                                      ("r", True, False, "p"), ("r", False, False, "u")])
def test_nonregular_or_policy_modified_table_is_rejected(relation):
    helper = load_helper()
    with pytest.raises(ValueError, match="target_request_table_mismatch"):
        helper._verify_request_schema(fake_connection([relation]), helper.TARGET)


@pytest.mark.parametrize("position,replacement", [
    (1, "text"), (2, "YES"), (3, 512), (4, "'pending'::text"), (5, "YES"), (6, "ALWAYS"),
])
def test_target_column_type_nullability_length_defaults_generation_are_exact(position, replacement):
    helper = load_helper()
    values = request_catalog(helper)
    index = next(i for i, row in enumerate(values[1]) if row[0] == "credential_hash")
    row = list(values[1][index])
    row[position] = replacement
    values[1][index] = tuple(row)
    with pytest.raises(ValueError, match="target_request_columns_mismatch"):
        helper._verify_request_schema(fake_connection(values), helper.TARGET)


@pytest.mark.parametrize("position,replacement", [
    (1, "u"), (2, False), (3, True), (4, True), (5, "CHECK (true)"),
    (5, "CHECK ((expires_at >= created_at))"),
])
def test_same_named_constraints_cannot_hide_different_semantics(position, replacement):
    helper = load_helper()
    values = request_catalog(helper)
    row = list(values[2][0])
    row[position] = replacement
    values[2][0] = tuple(row)
    with pytest.raises(ValueError, match="target_request_constraints_mismatch"):
        helper._verify_request_schema(fake_connection(values), helper.TARGET)


@pytest.mark.parametrize("position,replacement", [(1, False), (2, False), (3, False),
                                                  (4, "CREATE INDEX wrong ON other (id)")])
def test_invalid_unready_or_altered_index_is_rejected(position, replacement):
    helper = load_helper()
    values = request_catalog(helper)
    row = list(values[3][0])
    row[position] = replacement
    values[3][0] = tuple(row)
    with pytest.raises(ValueError, match="target_request_indexes_mismatch"):
        helper._verify_request_schema(fake_connection(values), helper.TARGET)


@pytest.mark.parametrize("section", [1, 2, 3])
def test_missing_or_additional_catalog_entities_are_rejected(section):
    helper = load_helper()
    for change in ("missing", "additional"):
        values = request_catalog(helper)
        if change == "missing":
            values[section].pop()
        else:
            values[section].append(values[section][-1])
        with pytest.raises(ValueError):
            helper._verify_request_schema(fake_connection(values), helper.TARGET)


def test_custom_trigger_is_rejected_and_expression_grouping_is_preserved():
    helper = load_helper()
    values = request_catalog(helper)
    values[4] = True
    with pytest.raises(ValueError, match="target_request_trigger_mismatch"):
        helper._verify_request_schema(fake_connection(values), helper.TARGET)
    assert helper._canonical_definition("CHECK ((a OR b) AND c)") != helper._canonical_definition(
        "CHECK (a OR (b AND c))"
    )
    assert helper._canonical_definition("CHECK (name = 'Win dows')") != helper._canonical_definition(
        "CHECK (name = 'Windows')"
    )


def test_authority_projection_retains_disabled_and_platform_fields():
    helper = load_helper()
    statements = []

    class Rows:
        def __iter__(self):
            return iter([('{"enabled": false, "device_platform": "macOS"}',)])

        def close(self):
            pass

    def execute(statement):
        statements.append(str(statement))
        return Rows()

    proof = helper._authority_snapshot(SimpleNamespace(execute=execute))
    assert len(proof) == 4 and all(row["count"] == 1 for row in proof.values())
    assert all(" - 'enabled'" not in statement and " - 'device_platform'" not in statement
               for statement in statements)
