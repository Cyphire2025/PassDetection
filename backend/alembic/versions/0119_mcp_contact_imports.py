"""Retain bounded agency-scoped spreadsheet imports and their business receipts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0119_mcp_contact_imports"
down_revision = "0118_mcp_pdf_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "mcp_contact_import_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("original_grant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_grants.id", ondelete="SET NULL")),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("handle_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("storage_key", sa.String(200), nullable=False, unique=True),
        sa.Column("filename", sa.String(120), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("workbook_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_operation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_operations.id", ondelete="RESTRICT"), unique=True),
        sa.Column("broadcast_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("whatsapp_broadcast_groups.id", ondelete="SET NULL")),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("byte_size BETWEEN 1 AND 5242880", name="ck_mcp_contact_upload_size"),
        sa.CheckConstraint("expires_at > created_at", name="ck_mcp_contact_upload_expiry"),
        sa.CheckConstraint("(consumed_operation_id IS NULL AND consumed_at IS NULL) OR (consumed_operation_id IS NOT NULL AND consumed_at IS NOT NULL)", name="ck_mcp_contact_upload_consumed"),
    )
    op.create_index("ix_mcp_contact_upload_expiry", "mcp_contact_import_uploads", ["expires_at"])
    op.create_index("ix_mcp_contact_upload_grant_created", "mcp_contact_import_uploads", ["original_grant_id", "created_at"])


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE mcp_contact_import_uploads IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM mcp_contact_import_uploads)")).scalar_one():
        raise RuntimeError("MCP contact source history must be retained; keep the additive schema during recovery.")
    op.drop_table("mcp_contact_import_uploads")
