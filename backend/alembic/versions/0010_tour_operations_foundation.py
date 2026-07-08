"""Add tour operations attendance foundation.

Revision ID: 0010_tour_operations_foundation
Revises: 0009_deleted_group_retention
Create Date: 2026-07-06 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_tour_operations_foundation"
down_revision = "0009_deleted_group_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'agency_coordinator'")

    attendance_session_status_enum = postgresql.ENUM(
        "draft",
        "active",
        "completed",
        "cancelled",
        name="attendance_session_status_enum",
        create_type=False,
    )
    attendance_session_status_enum.create(op.get_bind(), checkfirst=True)

    attendance_scan_source_enum = postgresql.ENUM(
        "online",
        "offline",
        name="attendance_scan_source_enum",
        create_type=False,
    )
    attendance_scan_source_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "coordinator_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("coordinator_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["coordinator_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["passenger_id"], ["passport_submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_coordinator_assignments_active", "coordinator_assignments", ["active"])
    op.create_index("ix_coordinator_assignments_agency_id", "coordinator_assignments", ["agency_id"])
    op.create_index("ix_coordinator_assignments_group_id", "coordinator_assignments", ["group_id"])
    op.create_index("ix_coordinator_assignments_passenger_id", "coordinator_assignments", ["passenger_id"])
    op.create_index("ix_coordinator_assignments_coordinator_user_id", "coordinator_assignments", ["coordinator_user_id"])
    op.create_index(
        "ix_coordinator_assignments_active_group",
        "coordinator_assignments",
        ["agency_id", "group_id", "active"],
    )
    op.create_index(
        "ix_coordinator_assignments_coordinator_active",
        "coordinator_assignments",
        ["coordinator_user_id", "active"],
    )
    op.create_index(
        "ix_coordinator_assignments_passenger_active",
        "coordinator_assignments",
        ["passenger_id", "active"],
    )

    op.create_table(
        "passenger_qr_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["passenger_id"], ["passport_submissions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_passenger_qr_tokens_token_hash"),
    )
    op.create_index("ix_passenger_qr_tokens_agency_id", "passenger_qr_tokens", ["agency_id"])
    op.create_index("ix_passenger_qr_tokens_passenger_id", "passenger_qr_tokens", ["passenger_id"])
    op.create_index("ix_passenger_qr_tokens_is_active", "passenger_qr_tokens", ["is_active"])
    op.create_index(
        "ix_passenger_qr_tokens_active_passenger",
        "passenger_qr_tokens",
        ["passenger_id", "is_active"],
    )
    op.create_index(
        "ix_passenger_qr_tokens_agency_active",
        "passenger_qr_tokens",
        ["agency_id", "is_active"],
    )
    op.create_index(
        "uq_passenger_qr_tokens_one_active_per_passenger",
        "passenger_qr_tokens",
        ["passenger_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
    )

    op.create_table(
        "attendance_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", attendance_session_status_enum, nullable=False, server_default="draft"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attendance_sessions_agency_id", "attendance_sessions", ["agency_id"])
    op.create_index("ix_attendance_sessions_group_id", "attendance_sessions", ["group_id"])
    op.create_index("ix_attendance_sessions_status", "attendance_sessions", ["status"])
    op.create_index("ix_attendance_sessions_group_status", "attendance_sessions", ["group_id", "status"])
    op.create_index("ix_attendance_sessions_agency_created", "attendance_sessions", ["agency_id", "created_at"])

    op.create_table(
        "attendance_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("coordinator_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sync_source", attendance_scan_source_enum, nullable=False, server_default="online"),
        sa.Column("client_event_id", sa.String(length=128), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["coordinator_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["passenger_id"], ["passport_submissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["attendance_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "client_event_id", name="uq_attendance_records_session_client_event"),
        sa.UniqueConstraint("session_id", "passenger_id", name="uq_attendance_records_session_passenger"),
    )
    op.create_index("ix_attendance_records_agency_id", "attendance_records", ["agency_id"])
    op.create_index("ix_attendance_records_session_id", "attendance_records", ["session_id"])
    op.create_index("ix_attendance_records_passenger_id", "attendance_records", ["passenger_id"])
    op.create_index("ix_attendance_records_coordinator_user_id", "attendance_records", ["coordinator_user_id"])
    op.create_index("ix_attendance_records_scanned_at", "attendance_records", ["scanned_at"])
    op.create_index("ix_attendance_records_agency_session", "attendance_records", ["agency_id", "session_id"])
    op.create_index(
        "ix_attendance_records_coordinator_scanned",
        "attendance_records",
        ["coordinator_user_id", "scanned_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_attendance_records_coordinator_scanned", table_name="attendance_records")
    op.drop_index("ix_attendance_records_agency_session", table_name="attendance_records")
    op.drop_index("ix_attendance_records_scanned_at", table_name="attendance_records")
    op.drop_index("ix_attendance_records_coordinator_user_id", table_name="attendance_records")
    op.drop_index("ix_attendance_records_passenger_id", table_name="attendance_records")
    op.drop_index("ix_attendance_records_session_id", table_name="attendance_records")
    op.drop_index("ix_attendance_records_agency_id", table_name="attendance_records")
    op.drop_table("attendance_records")

    op.drop_index("ix_attendance_sessions_agency_created", table_name="attendance_sessions")
    op.drop_index("ix_attendance_sessions_group_status", table_name="attendance_sessions")
    op.drop_index("ix_attendance_sessions_status", table_name="attendance_sessions")
    op.drop_index("ix_attendance_sessions_group_id", table_name="attendance_sessions")
    op.drop_index("ix_attendance_sessions_agency_id", table_name="attendance_sessions")
    op.drop_table("attendance_sessions")

    op.drop_index("uq_passenger_qr_tokens_one_active_per_passenger", table_name="passenger_qr_tokens")
    op.drop_index("ix_passenger_qr_tokens_agency_active", table_name="passenger_qr_tokens")
    op.drop_index("ix_passenger_qr_tokens_active_passenger", table_name="passenger_qr_tokens")
    op.drop_index("ix_passenger_qr_tokens_is_active", table_name="passenger_qr_tokens")
    op.drop_index("ix_passenger_qr_tokens_passenger_id", table_name="passenger_qr_tokens")
    op.drop_index("ix_passenger_qr_tokens_agency_id", table_name="passenger_qr_tokens")
    op.drop_table("passenger_qr_tokens")

    op.drop_index("ix_coordinator_assignments_passenger_active", table_name="coordinator_assignments")
    op.drop_index("ix_coordinator_assignments_coordinator_active", table_name="coordinator_assignments")
    op.drop_index("ix_coordinator_assignments_active_group", table_name="coordinator_assignments")
    op.drop_index("ix_coordinator_assignments_coordinator_user_id", table_name="coordinator_assignments")
    op.drop_index("ix_coordinator_assignments_passenger_id", table_name="coordinator_assignments")
    op.drop_index("ix_coordinator_assignments_group_id", table_name="coordinator_assignments")
    op.drop_index("ix_coordinator_assignments_agency_id", table_name="coordinator_assignments")
    op.drop_index("ix_coordinator_assignments_active", table_name="coordinator_assignments")
    op.drop_table("coordinator_assignments")

    op.execute("DROP TYPE IF EXISTS attendance_scan_source_enum")
    op.execute("DROP TYPE IF EXISTS attendance_session_status_enum")
