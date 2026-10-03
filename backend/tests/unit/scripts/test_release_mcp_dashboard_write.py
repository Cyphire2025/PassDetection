"""Closed source policy and exact new schema/profile drift rejection."""

import copy
import json
import sys
from pathlib import Path

import pytest

from tests.release_source_fixtures import dashboard_write_source

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from release_mcp_dashboard_write_contract import source_contract, validate_contract  # noqa: E402

from scripts import mcp_dashboard_write_schema as schema  # noqa: E402
from scripts.release_mcp_dashboard_write import POLICY, verify_sources  # noqa: E402


@pytest.fixture(autouse=True)
def historical_release_source(tmp_path, monkeypatch):
    """Qualify the original exact contract rather than the current release manifest."""
    pinned = dashboard_write_source(ROOT, tmp_path)
    monkeypatch.setattr(sys.modules[__name__], "ROOT", pinned)


def test_exact_contract_and_image_helper_policy_match():
    contract = source_contract(ROOT)
    validate_contract(contract, schema.TARGET)
    profile = verify_sources(ROOT / "backend", contract)
    assert {key: contract[key] for key in POLICY} == POLICY
    assert profile["schema"] == schema.TARGET and len(profile["new_tables"]) == 3
    assert (
        contract["export_source_row_limit"] == 100
        and contract["export_source_byte_limit"] == 1048576
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "mcp_admin_approval_v1"),
        ("source_schema", schema.TARGET),
        ("write_authority", "enabled"),
        ("existing_grants", "expand"),
        ("automatic_downgrade", True),
        ("allowed_capabilities", ["mcp:read", "mcp:diagnose"]),
        ("read_only_mode", True),
        ("export_source_row_limit", 1500),
        ("export_source_byte_limit", 16 * 1024 * 1024),
        ("new_tables", "populated"),
        ("existing_requests", "empty"),
        ("historical_rows", "timestamps_excluded"),
    ],
)
def test_authority_or_resource_policy_cannot_be_relaxed(field, value):
    contract = source_contract(ROOT)
    contract[field] = value
    with pytest.raises(ValueError):
        validate_contract(contract, schema.TARGET)
    with pytest.raises(ValueError):
        verify_sources(ROOT / "backend", contract)


@pytest.mark.parametrize("change", ["parent", "path", "order", "hash", "profile_hash", "extra"])
def test_exact_source_and_profile_binding_rejects_drift(change):
    value = source_contract(ROOT)
    if change in {"parent", "path", "hash"}:
        value["migrations"][0][{"hash": "sha256"}.get(change, change)] = "0" * 64
    elif change == "order":
        value["migrations"].reverse()
    elif change == "profile_hash":
        value["schema_profile"]["sha256"] = "0" * 64
    else:
        value["extra"] = "ignored"
    with pytest.raises(ValueError):
        verify_sources(ROOT / "backend", value)


def test_retained_catalog_excludes_only_reviewed_added_fields():
    profile = json.loads((ROOT / "backend/scripts/mcp_dashboard_write_schema.json").read_text())
    source = {
        "users": {
            "relation": ["r", False, False, "p"],
            "columns": [["id", "uuid"]],
            "constraints": [],
            "indexes": [],
            "triggers": [],
        }
    }
    source["mcp_grants"] = {
        "columns": [
            ["enabled", "boolean"],
            ["last_used_at", "timestamp"],
            ["capabilities", "jsonb"],
            *profile["permissions"]["mcp_grants"]["columns"],
        ],
        "constraints": [["old", "CHECKTRUE"], *profile["permissions"]["mcp_grants"]["constraints"]],
        "indexes": [],
        "triggers": [],
    }
    source.update(profile["new_tables"])
    result = schema.retained_catalog(copy.deepcopy(source))
    assert set(result) == {"users", "mcp_grants"}
    assert result["mcp_grants"]["columns"] == [
        ["enabled", "boolean"],
        ["last_used_at", "timestamp"],
        ["capabilities", "jsonb"],
    ]
    assert result["mcp_grants"]["constraints"] == [["old", "CHECKTRUE"]]


def test_canonical_predicate_keeps_grouping_and_literal_contents():
    assert schema.canonical("CHECK ((a OR b) AND c)") != schema.canonical("CHECK (a OR (b AND c))")
    assert schema.canonical("CHECK (x='read only')") != schema.canonical("CHECK (x='readonly')")
