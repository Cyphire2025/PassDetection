"""Single reviewed contract shared by host qualification and the packaged helper."""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

KIND = "companies_traveller_reuse_v1"
SOURCE = "0135_company_removal_history"
CHAIN = (
    "0136_returning_drafts",
    "0137_company_directory",
    "0138_verified_portal_lookup",
)
TARGET = CHAIN[-1]
POLICY = {
    "version": 3,
    "kind": KIND,
    "source_schema": SOURCE,
    "target_schema": TARGET,
    "resume_schema_revisions": list(CHAIN[:-1]),
    "migration_transactions": "one_transaction_per_revision_with_writer_fence",
    "control_enabled": "preserve_existing_state",
    "existing_grants": "retain_without_expansion",
    "historical_rows": "preserve_all_existing_columns",
    "preservation_baseline": "original_source_sha256_required_across_resume",
    "company_backfill": "none_preserve_existing_assignments",
    "reuse_authority": "preserve_existing_policy_and_evidence",
    "manager_history": "preserve_existing_rows_and_scope_constraints",
    "portal_actor_evidence": "add_verified_label_without_relabelling_existing_grants",
    "passport_lookup": "nullable_keyed_projection_backfilled_after_activation",
    "company_directory": "encrypted_derived_projection_backfilled_after_activation",
    "public_drafts": "isolated_expiring_rows_no_automatic_publication",
    "new_tables": "empty_before_activation",
    "new_table_runtime_grants": "require_existing_passport_dml_grantees",
    "recovery": "forward_repair_with_original_backup_and_writer_fence",
    "automatic_downgrade": False,
    "retention": {
        "existing_containers": "retain",
        "source_and_business_files": "retain",
        "backup_and_helper_artifacts": "retain",
        "cleanup": "prohibited",
    },
}


def migration_entries(backend: Path) -> list[dict[str, str]]:
    entries, parent = [], SOURCE
    for revision in CHAIN:
        relative = f"backend/alembic/versions/{revision}.py"
        path = backend / "alembic/versions" / f"{revision}.py"
        if path.is_symlink() or not path.is_file():
            raise ValueError("regular_migration_source_required")
        raw, identity = path.read_bytes(), {}
        for node in ast.parse(raw).body:
            if isinstance(node, ast.Assign):
                for name in node.targets:
                    if isinstance(name, ast.Name) and name.id in {
                        "revision", "down_revision", "branch_labels", "depends_on"
                    }:
                        if name.id in identity:
                            raise ValueError("ambiguous_migration_identity")
                        identity[name.id] = ast.literal_eval(node.value)
        if identity != {
            "revision": revision, "down_revision": parent,
            "branch_labels": None, "depends_on": None,
        }:
            raise ValueError("migration_ancestry_changed")
        entries.append({
            "revision": revision, "parent": parent, "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
        parent = revision
    return entries


def validate_contract(value: dict[str, Any], schema: str) -> None:
    if (
        not isinstance(value, dict) or schema != TARGET
        or set(value) != set(POLICY) | {"migrations"}
        or any(type(value[key]) is not type(expected) or value[key] != expected
               for key, expected in POLICY.items())
    ):
        raise ValueError("invalid_companies_traveller_release_contract")
    entries = value["migrations"]
    if not isinstance(entries, list) or len(entries) != len(CHAIN):
        raise ValueError("exact_migration_chain_required")
    parent = SOURCE
    for entry, revision in zip(entries, CHAIN, strict=True):
        if (
            not isinstance(entry, dict)
            or set(entry) != {"revision", "parent", "path", "sha256"}
            or (entry["revision"], entry["parent"], entry["path"])
            != (revision, parent, f"backend/alembic/versions/{revision}.py")
            or not isinstance(entry["sha256"], str)
            or re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]) is None
        ):
            raise ValueError("invalid_migration_binding")
        parent = revision


def verify_sources(backend: Path, contract: dict[str, Any]) -> None:
    validate_contract(contract, TARGET)
    if contract["migrations"] != migration_entries(backend):
        raise ValueError("migration_source_changed")


def remaining_revisions(schema: str) -> tuple[str, ...]:
    if schema == SOURCE:
        return CHAIN
    if schema not in CHAIN:
        raise ValueError("source_schema_mismatch")
    return CHAIN[CHAIN.index(schema) + 1:]
