"""Add explicit passport purge schedules and group legal holds.

Revision ID: 0085_platform_retention_controls
Revises: 0084_identity_lifecycle
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0085_platform_retention_controls"
down_revision = "0084_identity_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_groups",
        sa.Column("passport_purge_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "client_groups",
        sa.Column("passport_retention_days_applied", sa.Integer(), nullable=True),
    )
    op.add_column(
        "client_groups",
        sa.Column(
            "passport_legal_hold",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "client_groups",
        sa.Column("passport_legal_hold_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "client_groups",
        sa.Column(
            "passport_legal_hold_set_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "client_groups",
        sa.Column(
            "passport_legal_hold_set_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_client_groups_passport_legal_hold_user",
        "client_groups",
        "users",
        ["passport_legal_hold_set_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_client_groups_passport_retention_days_applied",
        "client_groups",
        "passport_retention_days_applied IS NULL OR "
        "passport_retention_days_applied BETWEEN 1 AND 3650",
    )
    op.create_check_constraint(
        "ck_client_groups_passport_legal_hold_shape",
        "client_groups",
        "(passport_legal_hold = false AND passport_legal_hold_reason IS NULL "
        "AND passport_legal_hold_set_at IS NULL "
        "AND passport_legal_hold_set_by_user_id IS NULL) OR "
        "(passport_legal_hold = true "
        "AND length(trim(passport_legal_hold_reason)) BETWEEN 3 AND 500 "
        "AND passport_legal_hold_set_at IS NOT NULL)",
    )
    op.create_index(
        "ix_client_groups_passport_retention_due",
        "client_groups",
        ["passport_legal_hold", "passport_purge_at", "id"],
    )

    # Existing closed data receives an explicit date during migration. Use the
    # persisted global policy when it has a safe integer shape; otherwise fall
    # back to the reviewed 365-day default rather than aborting a deployment.
    op.execute(
        """
        WITH retention_policy AS (
            SELECT CASE
                WHEN (value ->> 'passport_data_retention_days') ~ '^[0-9]{1,4}$'
                 AND (value ->> 'passport_data_retention_days')::integer BETWEEN 1 AND 3650
                THEN (value ->> 'passport_data_retention_days')::integer
                ELSE 365
            END AS retention_days
            FROM platform_settings
            WHERE key = 'global'
            LIMIT 1
        )
        UPDATE client_groups
        SET passport_retention_days_applied = COALESCE(
                (SELECT retention_days FROM retention_policy),
                365
            ),
            passport_purge_at = COALESCE(deleted_at, closed_at)
            + COALESCE(
                (SELECT retention_days FROM retention_policy),
                365
            ) * INTERVAL '1 day'
        WHERE status IN ('closed', 'archived', 'deleted')
          AND COALESCE(deleted_at, closed_at) IS NOT NULL
          AND passport_purge_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_client_groups_passport_retention_due",
        table_name="client_groups",
    )
    op.drop_constraint(
        "ck_client_groups_passport_retention_days_applied",
        "client_groups",
        type_="check",
    )
    op.drop_constraint(
        "ck_client_groups_passport_legal_hold_shape",
        "client_groups",
        type_="check",
    )
    op.drop_constraint(
        "fk_client_groups_passport_legal_hold_user",
        "client_groups",
        type_="foreignkey",
    )
    op.drop_column("client_groups", "passport_legal_hold_set_by_user_id")
    op.drop_column("client_groups", "passport_legal_hold_set_at")
    op.drop_column("client_groups", "passport_legal_hold_reason")
    op.drop_column("client_groups", "passport_legal_hold")
    op.drop_column("client_groups", "passport_retention_days_applied")
    op.drop_column("client_groups", "passport_purge_at")
