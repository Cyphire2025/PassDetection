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
        "direct_device_upgrade_unit", BACKEND / "scripts/apply_mcp_direct_devices_upgrade.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def contract():
    return runpy.run_path(str(ROOT / "scripts/release_mcp_direct_devices_contract.py"))[
        "source_contract"
    ](ROOT)


def test_exact_source_contract_is_accepted():
    load_helper().verify_sources(BACKEND, contract())


@pytest.mark.parametrize("field,value", [
    ("version", True),
    ("kind", "mcp_read_only_v1"),
    ("source_schema", "0122_mcp_gc_push"),
    ("target_schema", "0123_mcp_read_sections"),
    ("read_only_mode", False),
    ("allowed_capabilities", ["mcp:read", "mcp:export"]),
    ("control_enabled", True),
    ("existing_grants", "expand"),
    ("read_section_authority", "reset"),
    ("connection_enabled", "reset"),
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
    ("revision", "0123_mcp_read_sections"), ("extra", "arbitrary"),
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
    path = tmp_path / "alembic/versions/0124_mcp_device_access.py"
    path.parent.mkdir(parents=True)
    shutil.copyfile(BACKEND / "alembic/versions/0124_mcp_device_access.py", path)
    path.write_text(path.read_text("utf-8") + '\ndown_revision = "0123_mcp_read_sections"\n',
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
        "status": "failed", "reason": "direct_devices_upgrade_failed",
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
        helper._verify_columns(connection, helper.TARGET)
