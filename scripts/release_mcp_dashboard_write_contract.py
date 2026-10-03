"""Closed additive contract for mixed MCP code availability and default-denied writes."""

import ast
import hashlib
import json
from pathlib import Path

KIND = "mcp_dashboard_write_v1"
SOURCE = "0125_mcp_connection_requests"
CHAIN = (
    "0126_mcp_section_permissions",
    "0127_mcp_native_transfers",
    "0128_mcp_document_delivery",
)
TARGET = CHAIN[-1]
PROFILE = "backend/scripts/mcp_dashboard_write_schema.json"
POLICY = {
    "version": 1,
    "kind": KIND,
    "source_schema": SOURCE,
    "target_schema": TARGET,
    "read_only_mode": False,
    "export_source_row_limit": 100,
    "export_source_byte_limit": 1048576,
    "export_families": ["passport_excel", "passport_images", "tracking_excel", "rooming_excel", "document_assignments_excel"],
    "allowed_capabilities": [
        "mcp:read",
        "mcp:change",
        "mcp:upload",
        "mcp:export",
        "mcp:communicate",
    ],
    "control_enabled": "preserve_existing_state",
    "existing_grants": "retain_without_expansion",
    "read_section_authority": "preserve_existing_state",
    "connection_enabled": "preserve_existing_state",
    "existing_requests": "retain_without_expansion",
    "write_authority": "default_denied",
    "new_tables": "empty_before_activation",
    "historical_rows": "preserve_all_fields_except_added_permission_columns",
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
        (root / "backend/app/core/config/release_manifest.json").read_text("utf8")
    )
    if (
        manifest.get("deployment_kind"),
        manifest.get("previous_schema_revision"),
        manifest.get("schema_revision"),
    ) != (KIND, SOURCE, TARGET):
        raise ValueError("Exact dashboard write migration ancestry is required")
    parent, entries = SOURCE, []
    for revision in CHAIN:
        relative = f"backend/alembic/versions/{revision}.py"
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("Regular additive migration source required")
        raw, identities = path.read_bytes(), {}
        for node in ast.parse(raw).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {
                        "revision",
                        "down_revision",
                        "branch_labels",
                        "depends_on",
                    }:
                        if target.id in identities:
                            raise ValueError("Ambiguous migration identity")
                        identities[target.id] = ast.literal_eval(node.value)
        if identities != {
            "revision": revision,
            "down_revision": parent,
            "branch_labels": None,
            "depends_on": None,
        }:
            raise ValueError("Additive migration identity changed")
        entries.append(
            {
                "revision": revision,
                "parent": parent,
                "path": relative,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
        parent = revision
    profile = root / PROFILE
    if profile.is_symlink() or not profile.is_file():
        raise ValueError("Qualified target schema profile required")
    return {
        **POLICY,
        "migrations": entries,
        "schema_profile": {
            "path": PROFILE,
            "sha256": hashlib.sha256(profile.read_bytes()).hexdigest(),
        },
    }


def validate_contract(value: dict, schema: str) -> None:
    if (
        not isinstance(value, dict)
        or set(value) != set(POLICY) | {"migrations", "schema_profile"}
        or schema != TARGET
    ):
        raise ValueError("Malformed dashboard write contract")
    if any(
        type(value[key]) is not type(expected) or value[key] != expected
        for key, expected in POLICY.items()
    ):
        raise ValueError("Dashboard write authority policy changed")
    if not isinstance(value["migrations"], list) or len(value["migrations"]) != len(
        CHAIN
    ):
        raise ValueError("Exact additive migration chain required")
    parent = SOURCE
    for entry, revision in zip(value["migrations"], CHAIN, strict=True):
        if (
            not isinstance(entry, dict)
            or set(entry) != {"revision", "parent", "path", "sha256"}
            or (entry["revision"], entry["parent"], entry["path"])
            != (revision, parent, f"backend/alembic/versions/{revision}.py")
            or not _digest(entry["sha256"])
        ):
            raise ValueError("Invalid additive migration binding")
        parent = revision
    profile = value["schema_profile"]
    if (
        not isinstance(profile, dict)
        or set(profile) != {"path", "sha256"}
        or profile["path"] != PROFILE
        or not _digest(profile["sha256"])
    ):
        raise ValueError("Invalid qualified schema profile binding")


def _digest(value) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )
