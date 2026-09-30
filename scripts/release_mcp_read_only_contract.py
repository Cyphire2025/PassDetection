"""Source contract for the minimum read-only release; never executes a rollout.

The old initial MCP executor and every same-schema updater remain inapplicable.
The separately reviewed forward executor must fence writers, retain its backup,
and preserve the target schema during recovery.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

KIND = "mcp_read_only_v1"
SOURCE = "0122_mcp_gc_push"
TARGET = "0123_mcp_read_sections"
PATH = f"backend/alembic/versions/{TARGET}.py"
RETENTION = {
    "existing_containers": "retain",
    "source_and_business_files": "retain",
    "backup_and_helper_artifacts": "retain",
    "cleanup": "prohibited",
}


def source_contract(root: Path) -> dict:
    manifest = json.loads(
        (root / "backend/app/core/config/release_manifest.json").read_text("utf-8")
    )
    if (
        manifest.get("deployment_kind") != KIND
        or manifest.get("previous_schema_revision") != SOURCE
        or manifest.get("schema_revision") != TARGET
    ):
        raise ValueError(
            "Read-only MCP requires its exact reviewed source/target chain"
        )
    migration = root / PATH
    if migration.is_symlink() or not migration.is_file():
        raise ValueError("The read-only migration must be a regular source file")
    raw = migration.read_bytes()
    identities = {}
    for node in ast.parse(raw, filename=PATH).body:
        if isinstance(node, ast.Assign):
            for key in node.targets:
                if isinstance(key, ast.Name) and key.id in {
                    "revision",
                    "down_revision",
                    "branch_labels",
                    "depends_on",
                }:
                    if key.id in identities:
                        raise ValueError("Duplicate migration identity assignment")
                    identities[key.id] = ast.literal_eval(node.value)
    if identities != {
        "revision": TARGET,
        "down_revision": SOURCE,
        "branch_labels": None,
        "depends_on": None,
    }:
        raise ValueError(
            "Read-only MCP migration identity or ancestry differs from the reviewed chain"
        )
    return {
        "version": 1,
        "kind": KIND,
        "source_schema": SOURCE,
        "target_schema": TARGET,
        "migrations": [
            {
                "revision": TARGET,
                "parent": SOURCE,
                "path": PATH,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        ],
        "read_only_mode": True,
        "allowed_capabilities": ["mcp:read"],
        "control_enabled": "preserve_existing_state",
        "existing_grants": "retain_without_expansion",
        "recovery": "forward_repair_preserving_target_schema",
        "automatic_downgrade": False,
        "retention": dict(RETENTION),
    }


def validate_contract(value: dict, schema: str) -> None:
    keys = {
        "version",
        "kind",
        "source_schema",
        "target_schema",
        "migrations",
        "read_only_mode",
        "allowed_capabilities",
        "control_enabled",
        "existing_grants",
        "recovery",
        "automatic_downgrade",
        "retention",
    }
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["kind"] != KIND
        or value["source_schema"] != SOURCE
        or value["target_schema"] != TARGET
        or schema != TARGET
        or value["read_only_mode"] is not True
        or value["allowed_capabilities"] != ["mcp:read"]
        or value["control_enabled"] != "preserve_existing_state"
        or value["existing_grants"] != "retain_without_expansion"
        or value["recovery"] != "forward_repair_preserving_target_schema"
        or value["automatic_downgrade"] is not False
        or value["retention"] != RETENTION
    ):
        raise ValueError(
            "Read-only MCP deployment policy differs from the reviewed contract"
        )
    chain = value["migrations"]
    if not isinstance(chain, list) or len(chain) != 1:
        raise ValueError("Incomplete read-only MCP migration chain")
    entry = chain[0]
    if (
        not isinstance(entry, dict)
        or set(entry) != {"revision", "parent", "path", "sha256"}
        or entry["revision"] != TARGET
        or entry["parent"] != SOURCE
        or entry["path"] != PATH
        or not isinstance(entry["sha256"], str)
        or len(entry["sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in entry["sha256"])
    ):
        raise ValueError("Read-only MCP migration identity/hash is invalid")
