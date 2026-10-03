"""Exact additive tracker migration; preserve every existing authority and resource."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

KIND = "travel_tracker_additive_v1"
SOURCE = "0128_mcp_document_delivery"
TARGET = "0129_travel_tracker"
PATH = f"backend/alembic/versions/{TARGET}.py"
POLICY = {
    "version": 1,
    "kind": KIND,
    "source_schema": SOURCE,
    "target_schema": TARGET,
    "control_enabled": "preserve_existing_state",
    "existing_grants": "retain_without_expansion",
    "read_section_authority": "preserve_existing_state",
    "write_section_authority": "preserve_existing_state",
    "connection_enabled": "preserve_existing_state",
    "existing_requests": "retain_without_expansion",
    "settings": "preserve_existing_state",
    "historical_rows": "preserve_all_fields",
    "new_tables": "empty_before_activation",
    "new_table_runtime_grants": "require_existing_passport_dml_grantees",
    "recovery": "forward_repair_preserving_target_schema",
    "automatic_downgrade": False,
    "retention": {
        "existing_containers": "retain",
        "source_and_business_files": "retain",
        "backup_and_helper_artifacts": "retain",
        "cleanup": "prohibited",
    },
}


def source_contract(root: Path) -> dict:
    manifest = json.loads(
        (root / "backend/app/core/config/release_manifest.json").read_text("utf-8")
    )
    if (
        manifest.get("deployment_kind"),
        manifest.get("previous_schema_revision"),
        manifest.get("schema_revision"),
    ) != (KIND, SOURCE, TARGET):
        raise ValueError("Exact tracker source and target schema required")
    path = root / PATH
    if path.is_symlink() or not path.is_file():
        raise ValueError("Regular tracker migration source required")
    raw, identity = path.read_bytes(), {}
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign):
            for name in node.targets:
                if isinstance(name, ast.Name) and name.id in {
                    "revision",
                    "down_revision",
                    "branch_labels",
                    "depends_on",
                }:
                    if name.id in identity:
                        raise ValueError("Ambiguous migration identity")
                    identity[name.id] = ast.literal_eval(node.value)
    if identity != {
        "revision": TARGET,
        "down_revision": SOURCE,
        "branch_labels": None,
        "depends_on": None,
    }:
        raise ValueError("Tracker migration ancestry changed")
    return {
        **POLICY,
        "migrations": [
            {
                "revision": TARGET,
                "parent": SOURCE,
                "path": PATH,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        ],
    }


def validate_contract(value: dict, schema: str) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != set(POLICY) | {"migrations"}
        or schema != TARGET
    ):
        raise ValueError("Malformed tracker release contract")
    if any(
        type(value[key]) is not type(expected) or value[key] != expected
        for key, expected in POLICY.items()
    ):
        raise ValueError("Tracker authority or retention policy changed")
    entries = value["migrations"]
    if not isinstance(entries, list) or len(entries) != 1:
        raise ValueError("Exact tracker migration required")
    entry = entries[0]
    if (
        not isinstance(entry, dict)
        or set(entry) != {"revision", "parent", "path", "sha256"}
        or (entry["revision"], entry["parent"], entry["path"]) != (TARGET, SOURCE, PATH)
        or not isinstance(entry["sha256"], str)
        or re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]) is None
    ):
        raise ValueError("Invalid tracker migration binding")
