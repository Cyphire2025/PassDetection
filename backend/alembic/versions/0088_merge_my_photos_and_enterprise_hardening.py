"""Merge the My Photos and enterprise-hardening migration branches.

Revision ID: 0088_merge_my_photos_hardening
Revises: 0086_my_photos_foundation, 0087_enterprise_hardening

Both parent revisions intentionally descend from 0085. This no-op merge keeps
their histories immutable while restoring one deployable Alembic head.
"""

from __future__ import annotations

revision = "0088_merge_my_photos_hardening"
down_revision = (
    "0086_my_photos_foundation",
    "0087_enterprise_hardening",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join both already-applied parent revisions without changing schema."""


def downgrade() -> None:
    """Return to the two parent heads without reversing either feature."""
