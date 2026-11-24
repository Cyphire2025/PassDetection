"""Exact, additive 0140/0141 to 0142 private workspace image contract."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

SOURCE = "0140_document_update_context"
TARGET = "0142_group_background"
CHAIN = ("0141_workspace_branding", TARGET)
BASELINES = (SOURCE, CHAIN[0])
KIND = "workspace_branding_v1"
POLICY = {
    "version": 1,
    "kind": KIND,
    "source_schema": SOURCE,
    "target_schema": TARGET,
    "historical_rows": "preserve_all_existing_columns",
    "new_columns": "nullable_private_company_logo_group_banner_and_background_keys",
    "existing_grants": "retain_without_expansion",
    "automatic_downgrade": False,
}
REVIEWED_BRANDING = '''import sqlalchemy as sa
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


REVIEWED_BACKGROUND = '''import sqlalchemy as sa

from alembic import op

revision = "0142_group_background"
down_revision = "0141_workspace_branding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("client_groups", sa.Column("background_image_key", sa.String(512), nullable=True))


def downgrade() -> None:
    if op.get_bind().execute(sa.text(
        "SELECT 1 FROM client_groups WHERE background_image_key IS NOT NULL LIMIT 1"
    )).first():
        raise RuntimeError("Remove group backgrounds before downgrading; stored image references must be preserved")
    op.drop_column("client_groups", "background_image_key")
'''


def body(raw: str) -> str:
    tree = ast.parse(raw)
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
        tree.body.pop(0)
    return ast.dump(tree)


def migration_entries(backend: Path, source_schema: str = SOURCE) -> list[dict[str, str]]:
    if source_schema not in BASELINES:
        raise ValueError("source_schema_mismatch")
    entries = []
    for revision, parent, reviewed in (
        (CHAIN[0], SOURCE, REVIEWED_BRANDING),
        (TARGET, CHAIN[0], REVIEWED_BACKGROUND),
    ):
        path = backend / "alembic/versions" / f"{revision}.py"
        if path.is_symlink() or not path.is_file() or body(path.read_text("utf-8")) != body(reviewed):
            raise ValueError("exact_branding_migration_required")
        entries.append({"revision": revision, "parent": parent,
                        "path": f"backend/alembic/versions/{revision}.py",
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    remaining = remaining_revisions(source_schema)
    return [entry for entry in entries if entry["revision"] in remaining]


def validate_contract(value: dict, schema: str) -> None:
    if not isinstance(value, dict) or value.get("source_schema") not in BASELINES:
        raise ValueError("invalid_branding_release_contract")
    expected = {**POLICY, "source_schema": value["source_schema"]}
    if (schema != TARGET or set(value) != set(expected) | {"migrations"}
        or any(type(value[key]) is not type(item) or value[key] != item for key, item in expected.items())):
        raise ValueError("invalid_branding_release_contract")
    entries = value["migrations"]
    revisions = remaining_revisions(value["source_schema"])
    if not isinstance(entries, list) or len(entries) != len(revisions):
        raise ValueError("invalid_branding_migration_binding")
    parent = value["source_schema"]
    for entry, revision in zip(entries, revisions):
        if (not isinstance(entry, dict) or set(entry) != {"revision", "parent", "path", "sha256"}
            or entry != {"revision": revision, "parent": parent,
                         "path": f"backend/alembic/versions/{revision}.py", "sha256": entry["sha256"]}
            or not isinstance(entry["sha256"], str) or len(entry["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in entry["sha256"])):
            raise ValueError("invalid_branding_migration_binding")
        parent = revision


def verify_sources(backend: Path, contract: dict) -> None:
    validate_contract(contract, TARGET)
    if contract["migrations"] != migration_entries(backend, contract["source_schema"]):
        raise ValueError("branding_migration_source_changed")


def remaining_revisions(schema: str) -> tuple[str, ...]:
    if schema == SOURCE:
        return CHAIN
    if schema in CHAIN:
        return CHAIN[CHAIN.index(schema) + 1:]
    raise ValueError("source_schema_mismatch")
