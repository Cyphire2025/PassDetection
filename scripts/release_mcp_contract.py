"""Bind the reviewed MCP migration chain into signed image qualification metadata.

This module performs no deployment. An artifact declaring this release kind
requires a separately qualified migration-aware orchestrator; the same-schema
updater must refuse it, including when the target schema is already present.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

KIND = "mcp_additive_v1"
SOURCE = "0113_document_follow_up"
CHAIN = (
    "0114_mcp_connections", "0115_mcp_workflows", "0116_mcp_communications",
    "0117_mcp_dispatch_origin", "0118_mcp_pdf_ingestion", "0119_mcp_contact_imports",
    "0120_mcp_whatsapp_media", "0121_whatsapp_send_intents", "0122_mcp_gc_push",
)
RETENTION = {
    "existing_containers": "retain",
    "source_and_business_files": "retain",
    "backup_and_helper_artifacts": "retain",
    "cleanup": "prohibited",
}


def source_contract(root: Path) -> dict | None:
    manifest = json.loads((root / "backend/app/core/config/release_manifest.json").read_text("utf-8"))
    if manifest.get("deployment_kind") == "mcp_read_only_v1":
        from release_mcp_read_only_contract import source_contract as read_only_contract
        return read_only_contract(root)
    if "deployment_kind" not in manifest:
        return None  # Historical releases keep their existing contract.
    if (manifest["deployment_kind"] != KIND or manifest["previous_schema_revision"] != SOURCE
            or manifest["schema_revision"] != CHAIN[-1]):
        raise ValueError("The MCP release requires its exact reviewed source/target chain")
    chain, parent = [], SOURCE
    for revision in CHAIN:
        relative = f"backend/alembic/versions/{revision}.py"
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("A reviewed migration must be a regular source file")
        raw = path.read_bytes()
        assignments = {}
        for node in ast.parse(raw, filename=relative).body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision", "branch_labels", "depends_on"}:
                        if target.id in assignments:
                            raise ValueError("Duplicate migration identity assignment")
                        assignments[target.id] = ast.literal_eval(node.value)
        if assignments != {"revision": revision, "down_revision": parent, "branch_labels": None, "depends_on": None}:
            raise ValueError("MCP migration identity or ancestry differs from the reviewed linear chain")
        chain.append({"revision": revision, "parent": parent, "path": relative,
                      "sha256": hashlib.sha256(raw).hexdigest()})
        parent = revision
    return {"version": 1, "kind": KIND, "source_schema": SOURCE, "target_schema": CHAIN[-1],
            "migrations": chain, "initial_mcp_enabled": False,
            "initial_allowed_capabilities": ["mcp:read", "mcp:export"],
            "recovery": "forward_repair_preserving_target_schema", "automatic_downgrade": False,
            "retention": dict(RETENTION)}


def validate_contract(contract: dict, schema: str) -> None:
    """Validate signed metadata without treating it as a deployment permission."""
    if isinstance(contract, dict) and contract.get("kind") == "mcp_read_only_v1":
        from release_mcp_read_only_contract import (
            validate_contract as validate_read_only,
        )
        validate_read_only(contract, schema)
        return
    if not isinstance(contract, dict) or set(contract) != {
        "version", "kind", "source_schema", "target_schema", "migrations", "initial_mcp_enabled",
        "initial_allowed_capabilities", "recovery", "automatic_downgrade", "retention",
    }:
        raise ValueError("Malformed MCP additive release contract")
    if (type(contract["version"]) is not int or contract["version"] != 1 or contract["kind"] != KIND or contract["source_schema"] != SOURCE
            or contract["target_schema"] != CHAIN[-1] or schema != CHAIN[-1]
            or contract["initial_mcp_enabled"] is not False or contract["automatic_downgrade"] is not False
            or contract["initial_allowed_capabilities"] != ["mcp:read", "mcp:export"]
            or contract["retention"] != RETENTION
            or contract["recovery"] != "forward_repair_preserving_target_schema"):
        raise ValueError("MCP additive release policy differs from the reviewed contract")
    chain = contract["migrations"]
    if not isinstance(chain, list) or len(chain) != len(CHAIN):
        raise ValueError("Incomplete MCP migration chain")
    parent = SOURCE
    for entry, revision in zip(chain, CHAIN, strict=True):
        if (not isinstance(entry, dict) or set(entry) != {"revision", "parent", "path", "sha256"}
                or entry["revision"] != revision or entry["parent"] != parent
                or entry["path"] != f"backend/alembic/versions/{revision}.py"
                or not isinstance(entry["sha256"], str) or len(entry["sha256"]) != 64
                or any(character not in "0123456789abcdef" for character in entry["sha256"])):
            raise ValueError("MCP migration chain identity/hash is invalid")
        parent = revision


def require_source_contract(manifest: dict, root: Path) -> None:
    expected = source_contract(root)
    if manifest.get("deployment") != expected:
        raise ValueError("Signed deployment contract differs from the current reviewed migration source")


def require_same_schema_artifact(manifest: dict) -> None:
    if manifest.get("deployment") is not None:
        raise ValueError("This artifact requires its qualified additive-schema release path; same-schema recovery is prohibited")
