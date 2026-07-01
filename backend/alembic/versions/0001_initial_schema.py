"""Initial schema migration — all tables for Phase 1 + Phase 2

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-06-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── agencies ──────────────────────────────────────────────────────────────
    op.create_table(
        "agencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_agencies_email", "agencies", ["email"])

    # ── user_role_enum ────────────────────────────────────────────────────────
    user_role_enum = postgresql.ENUM(
        "super_admin", "agency_admin", "agency_staff",
        name="user_role_enum",
        create_type=False,
    )
    user_role_enum.create(op.get_bind(), checkfirst=True)

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # ── refresh_tokens ────────────────────────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_from_ip", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_refresh_tokens_token", "refresh_tokens", ["token"])
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    # ── upload_link_status_enum ───────────────────────────────────────────────
    upload_link_status_enum = postgresql.ENUM(
        "active", "used", "expired", "revoked",
        name="upload_link_status_enum",
        create_type=False,
    )
    upload_link_status_enum.create(op.get_bind(), checkfirst=True)

    # ── upload_links ──────────────────────────────────────────────────────────
    op.create_table(
        "upload_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_email", sa.String(255), nullable=False),
        sa.Column("client_name", sa.String(255), nullable=False),
        sa.Column("status", upload_link_status_enum, nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_upload_links_token", "upload_links", ["token"])
    op.create_index("ix_upload_links_client_email", "upload_links", ["client_email"])

    # ── submission_status_enum ────────────────────────────────────────────────
    submission_status_enum = postgresql.ENUM(
        "pending_upload", "uploaded", "processing",
        "review_required", "confirmed", "failed",
        name="submission_status_enum",
        create_type=False,
    )
    submission_status_enum.create(op.get_bind(), checkfirst=True)

    # ── passport_submissions ──────────────────────────────────────────────────
    op.create_table(
        "passport_submissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("upload_link_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_name", sa.String(255), nullable=False),
        sa.Column("client_email", sa.String(255), nullable=False),
        sa.Column("image_s3_key", sa.String(512), nullable=False),
        sa.Column("thumbnail_s3_key", sa.String(512), nullable=True),
        sa.Column("status", submission_status_enum, nullable=False, server_default="uploaded"),
        sa.Column("extracted_fields", postgresql.JSONB(), nullable=True),
        sa.Column("confirmed_fields", postgresql.JSONB(), nullable=True),
        sa.Column("overall_confidence", sa.Float(), nullable=True),
        sa.Column("mrz_raw", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["upload_link_id"], ["upload_links.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_passport_submissions_upload_link_id", "passport_submissions", ["upload_link_id"])
    op.create_index("ix_passport_submissions_agency_id", "passport_submissions", ["agency_id"])
    op.create_index("ix_passport_submissions_status", "passport_submissions", ["status"])


def downgrade() -> None:
    op.drop_table("passport_submissions")
    op.drop_table("upload_links")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.drop_table("agencies")

    for enum_name in [
        "submission_status_enum",
        "upload_link_status_enum",
        "user_role_enum",
    ]:
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
