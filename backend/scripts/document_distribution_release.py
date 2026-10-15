"""Exact additive document-distribution contract shared by host and image."""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
from typing import Any

KIND = "document_distribution_updates_v1"
SOURCE = "0138_verified_portal_lookup"
CHAIN = ("0139_passenger_display_name", "0140_document_update_context")
TARGET = CHAIN[-1]
POLICY = {
    "version": 1,
    "kind": KIND,
    "source_schema": SOURCE,
    "target_schema": TARGET,
    "resume_schema_revisions": list(CHAIN[:-1]),
    "migration_transactions": "one_transaction_per_revision_with_writer_fence",
    "existing_grants": "retain_without_expansion",
    "historical_rows": "preserve_all_existing_columns",
    "preservation_baseline": "original_source_sha256_required_across_resume",
    "new_columns": "only_nullable_display_name_and_document_update_context",
    "new_column_values": "null_before_activation_no_backfill",
    "identity_and_delivery_history": "preserve_existing_values_and_routing",
    "recovery": "forward_repair_with_original_backup_and_writer_fence",
    "automatic_downgrade": False,
    "retention": {
        "existing_containers": "retain",
        "source_and_business_files": "retain",
        "backup_and_helper_artifacts": "retain",
        "cleanup": "prohibited",
    },
}


def _reviewed_source(revision: str, parent: str) -> str:
    if revision == CHAIN[0]:
        extra, table, column, kind = "", "passport_submissions", "display_name", "sa.String(255)"
    else:
        extra, table, column, kind = "from sqlalchemy.dialects import postgresql\n", "whatsapp_message_logs", "document_update_context", "postgresql.JSONB()"
    return f'''import sqlalchemy as sa
{extra}from alembic import op
revision = {revision!r}
down_revision = {parent!r}
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column({table!r}, sa.Column({column!r}, {kind}, nullable=True))
def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column({table!r}, {column!r})
'''


def _body(source: bytes | str) -> str:
    tree = ast.parse(source)
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
        tree.body.pop(0)
    return ast.dump(tree, include_attributes=False)


def migration_entries(backend: Path) -> list[dict[str, str]]:
    entries, parent = [], SOURCE
    for revision in CHAIN:
        relative = f"backend/alembic/versions/{revision}.py"
        path = backend / "alembic/versions" / f"{revision}.py"
        if path.is_symlink() or not path.is_file():
            raise ValueError("regular_migration_source_required")
        raw = path.read_bytes()
        if _body(raw) != _body(_reviewed_source(revision, parent)):
            raise ValueError("exact_document_migration_source_required")
        entries.append({"revision": revision, "parent": parent, "path": relative,
            "sha256": hashlib.sha256(raw).hexdigest()})
        parent = revision
    return entries


def validate_contract(value: dict[str, Any], schema: str) -> None:
    if (not isinstance(value, dict) or schema != TARGET
        or set(value) != set(POLICY) | {"migrations"}
        or any(type(value[key]) is not type(expected) or value[key] != expected
               for key, expected in POLICY.items())):
        raise ValueError("invalid_document_distribution_release_contract")
    entries = value["migrations"]
    if not isinstance(entries, list) or len(entries) != len(CHAIN):
        raise ValueError("exact_migration_chain_required")
    parent = SOURCE
    for entry, revision in zip(entries, CHAIN, strict=True):
        if (not isinstance(entry, dict) or set(entry) != {"revision", "parent", "path", "sha256"}
            or (entry["revision"], entry["parent"], entry["path"])
            != (revision, parent, f"backend/alembic/versions/{revision}.py")
            or not isinstance(entry["sha256"], str)
            or re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]) is None):
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
