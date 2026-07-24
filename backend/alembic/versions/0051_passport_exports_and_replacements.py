"""Add passport export checkpoints and unidentified-upload resolutions.

Revision ID: 0051_exports_replacements
Revises: 0050_whatsapp_roster_order
Create Date: 2026-07-24
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0051_exports_replacements"
down_revision = "0050_whatsapp_roster_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "passport_export_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("export_kind", sa.String(length=32), nullable=False),
        sa.Column("export_mode", sa.String(length=20), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "format_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "baseline_export_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "snapshot_submission_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "exported_submission_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "exported_people_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "total_available_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "exported_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "pending_recipient_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "artifact_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'prepared'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "export_kind IN ('passport_images', 'passport_excel')",
            name="ck_passport_export_history_kind",
        ),
        sa.CheckConstraint(
            "export_mode IN ('all', 'incremental')",
            name="ck_passport_export_history_mode",
        ),
        sa.CheckConstraint(
            "total_available_count >= 0 AND exported_count >= 0 AND pending_recipient_count >= 0",
            name="ck_passport_export_history_counts",
        ),
        sa.CheckConstraint(
            "format_version >= 1",
            name="ck_passport_export_history_format_version",
        ),
        sa.CheckConstraint(
            "(status = 'prepared' AND completed_at IS NULL) "
            "OR (status = 'completed' AND completed_at IS NOT NULL)",
            name="ck_passport_export_history_completion",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["baseline_export_id"],
            ["passport_export_history.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["client_groups.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "group_id",
            "export_kind",
            "request_id",
            name="uq_passport_export_history_group_kind_request",
        ),
    )
    op.create_index(
        "ix_passport_export_history_agency_id",
        "passport_export_history",
        ["agency_id"],
    )
    op.create_index(
        "ix_passport_export_history_baseline_export_id",
        "passport_export_history",
        ["baseline_export_id"],
    )
    op.create_index(
        "ix_passport_export_history_created_by_user_id",
        "passport_export_history",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_passport_export_history_group_id",
        "passport_export_history",
        ["group_id"],
    )
    op.create_index(
        "ix_passport_export_history_group_kind_created",
        "passport_export_history",
        ["group_id", "export_kind", "created_at"],
    )
    op.create_index(
        "ix_passport_export_history_group_kind_status_completed",
        "passport_export_history",
        ["group_id", "export_kind", "status", "completed_at"],
    )

    op.create_table(
        "passport_roster_resolutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "client_group_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "broadcast_recipient_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "replaced_recipient_normalized_phone",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "original_recipient_name",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "original_recipient_phone",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "original_recipient_imported_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("resolution_type", sa.String(length=24), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "suppressed_recipient_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "excluded_submission_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "resolved_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "restored_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "resolution_type IN ('replacement', 'rejected')",
            name="ck_passport_roster_resolution_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'restored')",
            name="ck_passport_roster_resolution_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND restored_at IS NULL) "
            "OR (status = 'restored' AND restored_at IS NOT NULL)",
            name="ck_passport_roster_resolution_restored_at",
        ),
        sa.CheckConstraint(
            "(resolution_type = 'replacement' "
            "AND replaced_recipient_normalized_phone IS NOT NULL "
            "AND original_recipient_phone IS NOT NULL "
            "AND (status = 'restored' OR broadcast_recipient_id IS NOT NULL)) "
            "OR (resolution_type = 'rejected' "
            "AND broadcast_recipient_id IS NULL "
            "AND replaced_recipient_normalized_phone IS NULL)",
            name="ck_passport_roster_resolution_recipient",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["broadcast_recipient_id"],
            ["whatsapp_broadcast_recipients.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["client_group_id"],
            ["client_groups.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["restored_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"],
            ["passport_submissions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "client_group_id",
            "request_id",
            name="uq_passport_roster_resolution_group_request",
        ),
    )
    op.create_index(
        "ix_passport_roster_resolutions_agency_id",
        "passport_roster_resolutions",
        ["agency_id"],
    )
    op.create_index(
        "ix_passport_roster_resolutions_broadcast_recipient_id",
        "passport_roster_resolutions",
        ["broadcast_recipient_id"],
    )
    op.create_index(
        "ix_passport_roster_resolutions_client_group_id",
        "passport_roster_resolutions",
        ["client_group_id"],
    )
    op.create_index(
        "ix_passport_roster_resolutions_group_status_created",
        "passport_roster_resolutions",
        ["client_group_id", "status", "created_at"],
    )
    op.create_index(
        "ix_passport_roster_resolutions_active_phone",
        "passport_roster_resolutions",
        ["agency_id", "client_group_id", "replaced_recipient_normalized_phone"],
        postgresql_where=sa.text(
            "status = 'active' AND resolution_type = 'replacement'"
        ),
    )
    op.create_index(
        "ix_passport_roster_resolutions_submission_id",
        "passport_roster_resolutions",
        ["submission_id"],
    )
    op.create_index(
        "uq_passport_roster_resolutions_active_recipient",
        "passport_roster_resolutions",
        ["broadcast_recipient_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND broadcast_recipient_id IS NOT NULL"),
    )
    op.create_index(
        "uq_passport_roster_resolutions_active_submission",
        "passport_roster_resolutions",
        ["submission_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.add_column(
        "whatsapp_broadcast_recipients",
        sa.Column(
            "suppressed_by_roster_resolution_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_whatsapp_recipient_roster_resolution",
        "whatsapp_broadcast_recipients",
        "passport_roster_resolutions",
        ["suppressed_by_roster_resolution_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_whatsapp_broadcast_recipients_roster_resolution",
        "whatsapp_broadcast_recipients",
        ["suppressed_by_roster_resolution_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_whatsapp_broadcast_recipients_roster_resolution",
        table_name="whatsapp_broadcast_recipients",
    )
    op.drop_constraint(
        "fk_whatsapp_recipient_roster_resolution",
        "whatsapp_broadcast_recipients",
        type_="foreignkey",
    )
    op.drop_column(
        "whatsapp_broadcast_recipients",
        "suppressed_by_roster_resolution_id",
    )
    op.drop_index(
        "uq_passport_roster_resolutions_active_submission",
        table_name="passport_roster_resolutions",
    )
    op.drop_index(
        "uq_passport_roster_resolutions_active_recipient",
        table_name="passport_roster_resolutions",
    )
    op.drop_index(
        "ix_passport_roster_resolutions_submission_id",
        table_name="passport_roster_resolutions",
    )
    op.drop_index(
        "ix_passport_roster_resolutions_active_phone",
        table_name="passport_roster_resolutions",
    )
    op.drop_index(
        "ix_passport_roster_resolutions_group_status_created",
        table_name="passport_roster_resolutions",
    )
    op.drop_index(
        "ix_passport_roster_resolutions_client_group_id",
        table_name="passport_roster_resolutions",
    )
    op.drop_index(
        "ix_passport_roster_resolutions_broadcast_recipient_id",
        table_name="passport_roster_resolutions",
    )
    op.drop_index(
        "ix_passport_roster_resolutions_agency_id",
        table_name="passport_roster_resolutions",
    )
    op.drop_table("passport_roster_resolutions")

    op.drop_index(
        "ix_passport_export_history_group_kind_status_completed",
        table_name="passport_export_history",
    )
    op.drop_index(
        "ix_passport_export_history_group_kind_created",
        table_name="passport_export_history",
    )
    op.drop_index(
        "ix_passport_export_history_group_id",
        table_name="passport_export_history",
    )
    op.drop_index(
        "ix_passport_export_history_created_by_user_id",
        table_name="passport_export_history",
    )
    op.drop_index(
        "ix_passport_export_history_baseline_export_id",
        table_name="passport_export_history",
    )
    op.drop_index(
        "ix_passport_export_history_agency_id",
        table_name="passport_export_history",
    )
    op.drop_table("passport_export_history")
