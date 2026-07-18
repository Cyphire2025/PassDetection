"""Add persisted Relation with Qualifier selections and submission snapshots.

Revision ID: 0037_relation_qualifier
Revises: 0036_whatsapp_delivery
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0037_relation_qualifier"
down_revision = "0036_whatsapp_delivery"
branch_labels = None
depends_on = None

_RELATION_CODES = (
    "spouse",
    "husband",
    "wife",
    "brother",
    "sister",
    "son",
    "daughter",
    "father",
    "mother",
    "parent",
    "child",
    "grandfather",
    "grandmother",
    "grandson",
    "granddaughter",
    "father_in_law",
    "mother_in_law",
    "brother_in_law",
    "sister_in_law",
    "son_in_law",
    "daughter_in_law",
    "legal_guardian",
)
_RELATION_CODE_SQL = ", ".join(f"'{code}'" for code in _RELATION_CODES)


def upgrade() -> None:
    op.add_column(
        "client_groups",
        sa.Column(
            "relation_with_qualifier_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_table(
        "qualifier_selections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("is_self", sa.Boolean(), nullable=False),
        sa.Column("relation_code", sa.String(length=40), nullable=True),
        sa.Column("relation_label", sa.String(length=80), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "("
            "is_self = true AND relation_code IS NULL AND relation_label = 'Self'"
            ") OR ("
            "is_self = false AND relation_code IS NOT NULL AND relation_label <> 'Self'"
            ")",
            name="ck_qualifier_selections_choice",
        ),
        sa.CheckConstraint(
            f"relation_code IS NULL OR relation_code IN ({_RELATION_CODE_SQL})",
            name="ck_qualifier_selections_relation_code",
        ),
        sa.CheckConstraint(
            "expires_at > selected_at",
            name="ck_qualifier_selections_expiry",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["client_groups.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "group_id",
            name="uq_qualifier_selections_id_group",
        ),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_qualifier_selections_token_hash",
        ),
    )
    op.create_index(
        "ix_qualifier_selections_group_id",
        "qualifier_selections",
        ["group_id"],
    )
    op.create_index(
        "ix_qualifier_selections_group_expires",
        "qualifier_selections",
        ["group_id", "expires_at"],
    )

    op.add_column(
        "passport_submissions",
        sa.Column(
            "qualifier_enabled_snapshot",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "passport_submissions",
        sa.Column(
            "qualifier_selection_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "passport_submissions",
        sa.Column("qualifier_is_self", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "passport_submissions",
        sa.Column("qualifier_relation_code", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "passport_submissions",
        sa.Column("qualifier_relation_label", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "passport_submissions",
        sa.Column("qualifier_selected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_passport_submissions_qualifier_selection",
        "passport_submissions",
        "qualifier_selections",
        ["qualifier_selection_id", "group_id"],
        ["id", "group_id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_passport_submissions_qualifier_selection",
        "passport_submissions",
        ["qualifier_selection_id"],
    )
    op.create_check_constraint(
        "ck_passport_submissions_qualifier_relation_code",
        "passport_submissions",
        (
            "qualifier_relation_code IS NULL OR "
            f"qualifier_relation_code IN ({_RELATION_CODE_SQL})"
        ),
    )
    op.create_check_constraint(
        "ck_passport_submissions_qualifier_snapshot",
        "passport_submissions",
        (
            "("
            "qualifier_enabled_snapshot = false AND "
            "qualifier_selection_id IS NULL AND "
            "qualifier_is_self IS NULL AND "
            "qualifier_relation_code IS NULL AND "
            "qualifier_relation_label IS NULL AND "
            "qualifier_selected_at IS NULL"
            ") OR ("
            "qualifier_enabled_snapshot = true AND "
            "qualifier_selection_id IS NOT NULL AND "
            "qualifier_is_self IS NOT NULL AND "
            "qualifier_relation_label IS NOT NULL AND "
            "qualifier_selected_at IS NOT NULL AND ("
            "(qualifier_is_self = true AND "
            "qualifier_relation_code IS NULL AND "
            "qualifier_relation_label = 'Self') OR "
            "(qualifier_is_self = false AND "
            "qualifier_relation_code IS NOT NULL AND "
            "qualifier_relation_label <> 'Self')"
            ")"
            ")"
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_passport_submissions_qualifier_snapshot",
        "passport_submissions",
        type_="check",
    )
    op.drop_constraint(
        "ck_passport_submissions_qualifier_relation_code",
        "passport_submissions",
        type_="check",
    )
    op.drop_constraint(
        "uq_passport_submissions_qualifier_selection",
        "passport_submissions",
        type_="unique",
    )
    op.drop_constraint(
        "fk_passport_submissions_qualifier_selection",
        "passport_submissions",
        type_="foreignkey",
    )
    op.drop_column("passport_submissions", "qualifier_selected_at")
    op.drop_column("passport_submissions", "qualifier_relation_label")
    op.drop_column("passport_submissions", "qualifier_relation_code")
    op.drop_column("passport_submissions", "qualifier_is_self")
    op.drop_column("passport_submissions", "qualifier_selection_id")
    op.drop_column("passport_submissions", "qualifier_enabled_snapshot")

    op.drop_index(
        "ix_qualifier_selections_group_expires",
        table_name="qualifier_selections",
    )
    op.drop_index(
        "ix_qualifier_selections_group_id",
        table_name="qualifier_selections",
    )
    op.drop_table("qualifier_selections")
    op.drop_column("client_groups", "relation_with_qualifier_enabled")
