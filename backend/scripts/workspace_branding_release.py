"""Exact, additive 0140 to 0141 private workspace image contract."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

SOURCE = "0140_document_update_context"
TARGET = "0141_workspace_branding"
CHAIN = (TARGET,)
KIND = "workspace_branding_v1"
POLICY = {
    "version": 1,
    "kind": KIND,
    "source_schema": SOURCE,
    "target_schema": TARGET,
    "historical_rows": "preserve_all_existing_columns",
    "new_columns": "nullable_private_company_logo_and_group_banner_keys",
    "existing_grants": "retain_without_expansion",
    "automatic_downgrade": False,
}
REVIEWED = '''import sqlalchemy as sa
from alembic import op
revision = "0141_workspace_branding"
down_revision = "0140_document_update_context"
branch_labels = None
depends_on = None
def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("client_organizations", sa.Column("logo_image_key", sa.String(512), nullable=True))
    op.add_column("client_groups", sa.Column("banner_image_key", sa.String(512), nullable=True))
def downgrade() -> None:
    op.drop_column("client_groups", "banner_image_key")
    op.drop_column("client_organizations", "logo_image_key")
'''


def body(raw: str) -> str:
    tree = ast.parse(raw)
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
        tree.body.pop(0)
    return ast.dump(tree)


def migration_entries(backend: Path) -> list[dict[str, str]]:
    relative = f"backend/alembic/versions/{TARGET}.py"
    path = backend / "alembic/versions" / f"{TARGET}.py"
    if path.is_symlink() or not path.is_file() or body(path.read_text("utf-8")) != body(REVIEWED):
        raise ValueError("exact_branding_migration_required")
    return [{"revision": TARGET, "parent": SOURCE, "path": relative,
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]


def validate_contract(value: dict, schema: str) -> None:
    if (schema != TARGET or not isinstance(value, dict) or set(value) != set(POLICY) | {"migrations"}
        or any(type(value[key]) is not type(expected) or value[key] != expected for key, expected in POLICY.items())):
        raise ValueError("invalid_branding_release_contract")
    entries = value["migrations"]
    if (not isinstance(entries, list) or len(entries) != 1 or set(entries[0]) != {"revision", "parent", "path", "sha256"}
        or entries[0] != {"revision": TARGET, "parent": SOURCE, "path": f"backend/alembic/versions/{TARGET}.py", "sha256": entries[0]["sha256"]}
        or not isinstance(entries[0]["sha256"], str) or len(entries[0]["sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in entries[0]["sha256"])):
        raise ValueError("invalid_branding_migration_binding")


def verify_sources(backend: Path, contract: dict) -> None:
    validate_contract(contract, TARGET)
    if contract["migrations"] != migration_entries(backend):
        raise ValueError("branding_migration_source_changed")


def remaining_revisions(schema: str) -> tuple[str, ...]:
    if schema == SOURCE:
        return CHAIN
    if schema == TARGET:
        return ()
    raise ValueError("source_schema_mismatch")
