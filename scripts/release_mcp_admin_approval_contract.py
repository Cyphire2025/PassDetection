"""Source-only contract for dashboard approval of native MCP requests; never executes rollout.

Existing read-only deployment authority remains unchanged. The historical
read-only and initial-MCP executors cannot apply this distinct release kind.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

KIND = "mcp_admin_approval_v1"
SOURCE = "0124_mcp_device_access"
TARGET = "0125_mcp_connection_requests"
PATH = f"backend/alembic/versions/{TARGET}.py"
RETENTION = {
    "existing_containers": "retain",
    "source_and_business_files": "retain",
    "backup_and_helper_artifacts": "retain",
    "cleanup": "prohibited",
}
POLICY = {
    "version": 1,
    "kind": KIND,
    "source_schema": SOURCE,
    "target_schema": TARGET,
    "read_only_mode": True,
    "allowed_capabilities": ["mcp:read"],
    "control_enabled": "preserve_existing_state",
    "existing_grants": "retain_without_expansion",
    "read_section_authority": "preserve_existing_state",
    "connection_enabled": "preserve_existing_state",
    "pending_requests": "empty_before_activation",
    "recovery": "forward_repair_preserving_target_schema",
    "automatic_downgrade": False,
    "retention": RETENTION,
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
        raise ValueError("MCP admin approval require their exact reviewed source/target chain")
    migration = root / PATH
    if migration.is_symlink() or not migration.is_file():
        raise ValueError("The connection request migration must be a regular source file")
    raw = migration.read_bytes()
    identities = {}
    for node in ast.parse(raw, filename=PATH).body:
        if isinstance(node, ast.Assign):
            for key in node.targets:
                if isinstance(key, ast.Name) and key.id in {
                    "revision", "down_revision", "branch_labels", "depends_on",
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
        raise ValueError("Connection request migration ancestry differs from the reviewed chain")
    return {
        **POLICY,
        "allowed_capabilities": list(POLICY["allowed_capabilities"]),
        "retention": dict(RETENTION),
        "migrations": [{
            "revision": TARGET,
            "parent": SOURCE,
            "path": PATH,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }],
    }


def validate_contract(value: dict, schema: str) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != set(POLICY) | {"migrations"}
        or schema != TARGET
        or any(
            type(value[key]) is not type(expected) or value[key] != expected
            for key, expected in POLICY.items()
        )
    ):
        raise ValueError("MCP admin approval policy differs from the reviewed contract")
    chain = value["migrations"]
    if not isinstance(chain, list) or len(chain) != 1:
        raise ValueError("Incomplete MCP admin approval migration chain")
    entry = chain[0]
    if (
        not isinstance(entry, dict)
        or set(entry) != {"revision", "parent", "path", "sha256"}
        or entry["revision"] != TARGET
        or entry["parent"] != SOURCE
        or entry["path"] != PATH
        or not isinstance(entry["sha256"], str)
        or len(entry["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in entry["sha256"])
    ):
        raise ValueError("MCP admin approval migration identity/hash is invalid")
