"""Add pending native OAuth requests without changing issued MCP authority."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0125_mcp_connection_requests"
down_revision = "0124_mcp_device_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE mcp_control,mcp_grants,mcp_tokens,mcp_authorization_codes IN SHARE MODE")
    op.create_table(
        "mcp_connection_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("comparison_code", sa.String(9), nullable=False),
        sa.Column("client_id", sa.String(200), nullable=False),
        sa.Column("redirect_uri", sa.String(1024), nullable=False),
        sa.Column("resource", sa.String(512), nullable=False),
        sa.Column("oauth_state", sa.String(512), nullable=False),
        sa.Column("code_challenge", sa.String(43), nullable=False),
        sa.Column("requested_capabilities", postgresql.JSONB(), nullable=False),
        sa.Column("approved_capabilities", postgresql.JSONB(), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("device_platform", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decision_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("security_version", sa.Integer(), nullable=True),
        sa.Column("mfa_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "grant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_grants.id", ondelete="RESTRICT"),
            nullable=True,
            unique=True,
        ),
        sa.CheckConstraint(
            "status IN ('pending','approved','rejected','finalized')", name="ck_mcp_request_status"
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_mcp_request_expiry"),
        sa.CheckConstraint(
            "device_platform IN ('Windows','macOS','Other')", name="ck_mcp_request_platform"
        ),
        sa.CheckConstraint(
            "security_version IS NULL OR security_version >= 1",
            name="ck_mcp_request_security_version",
        ),
    )
    op.create_index(
        "ix_mcp_requests_status_created", "mcp_connection_requests", ["status", "created_at"]
    )
    op.create_index(
        "ix_mcp_requests_source_created", "mcp_connection_requests", ["source_hash", "created_at"]
    )


def downgrade() -> None:
    raise RuntimeError(
        "Retain pending approval decisions and use a schema-compatible recovery image; destructive downgrade is unsupported"
    )
