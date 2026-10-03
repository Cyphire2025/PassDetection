"""Add constrained native file handoffs without changing issued authority."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0127_mcp_native_transfers"
down_revision = "0126_mcp_section_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "LOCK TABLE mcp_control,mcp_grants,mcp_tokens,mcp_authorization_codes,mcp_connection_requests IN SHARE MODE"
    )
    op.create_table(
        "mcp_native_transfers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "original_grant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_grants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("security_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True)),
        sa.Column("document_type", sa.String(40)),
        sa.Column("filename", sa.String(120), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("idempotency_hash", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True)),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "workbook_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_contact_import_uploads.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_artifacts.id", ondelete="SET NULL"),
        ),
        sa.Column("download_completed_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "kind IN ('upload_workbook','upload_pdf','download')",
            name="ck_mcp_native_transfer_kind",
        ),
        sa.CheckConstraint(
            "purpose IN ('contact_broadcast','group_workbook','document_pdf','export')",
            name="ck_mcp_native_transfer_purpose",
        ),
        sa.CheckConstraint(
            "status IN ('pending','transferring','completed','failed')",
            name="ck_mcp_native_transfer_status",
        ),
        sa.CheckConstraint("byte_size > 0", name="ck_mcp_native_transfer_size"),
        sa.CheckConstraint("security_version >= 1", name="ck_mcp_native_transfer_security"),
        sa.CheckConstraint("expires_at > created_at", name="ck_mcp_native_transfer_expiry"),
        sa.CheckConstraint(
            "(kind='upload_workbook' AND purpose IN ('contact_broadcast','group_workbook')) OR (kind='upload_pdf' AND purpose='document_pdf') OR (kind='download' AND purpose='export')",
            name="ck_mcp_native_transfer_lane",
        ),
        sa.UniqueConstraint(
            "original_grant_id", "kind", "idempotency_hash", name="uq_mcp_native_transfer_retry"
        ),
    )
    op.create_index(
        "ix_mcp_native_transfer_grant_created",
        "mcp_native_transfers",
        ["original_grant_id", "created_at"],
    )
    op.create_index("ix_mcp_native_transfer_expiry", "mcp_native_transfers", ["expires_at"])


def downgrade() -> None:
    raise RuntimeError(
        "Retain native handoff provenance and use a schema-compatible recovery image; destructive downgrade is unsupported"
    )
