"""Retain reviewed corrections and grant-specific access to protected artifacts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0115_mcp_workflows"
down_revision = "0114_mcp_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("mcp_artifacts", sa.Column(
        "association_groups", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.execute("""
        UPDATE mcp_artifacts SET association_groups = jsonb_build_array(
            jsonb_build_object('agency_id', agency_id::text, 'group_id', group_id::text))
    """)
    op.create_table(
        "mcp_artifact_access",
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_artifacts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("grant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_grants.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("handle_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("handle_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("handle_version IN (0, 1)", name="ck_mcp_artifact_access_version"),
    )
    op.execute("""
        INSERT INTO mcp_artifact_access (artifact_id, grant_id, handle_hash, handle_version, created_at)
        SELECT id, grant_id, handle_hash, 0, created_at FROM mcp_artifacts
    """)
    op.create_table(
        "mcp_record_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mcp_operations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("passport_submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("before_values", postgresql.JSONB(), nullable=False),
        sa.Column("after_values", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("entity_type = 'passport_submission'", name="ck_mcp_record_revision_entity"),
        sa.UniqueConstraint("operation_id", "entity_type", "entity_id", name="uq_mcp_record_revision_operation_entity"),
    )
    op.create_index("ix_mcp_record_revisions_entity_created", "mcp_record_revisions", ["entity_id", "created_at"])
    op.create_index("ix_mcp_record_revisions_agency_group_created", "mcp_record_revisions", ["agency_id", "group_id", "created_at"])


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE mcp_artifacts, mcp_artifact_access, mcp_record_revisions IN ACCESS EXCLUSIVE MODE")
    retained = op.get_bind().execute(sa.text("""
        SELECT EXISTS (SELECT 1 FROM mcp_record_revisions)
        OR EXISTS (
            SELECT 1 FROM mcp_artifact_access access
            JOIN mcp_artifacts artifact ON artifact.id = access.artifact_id
            WHERE access.handle_version != 0 OR access.grant_id != artifact.grant_id
                OR access.handle_hash != artifact.handle_hash)
        OR EXISTS (
            SELECT 1 FROM mcp_artifacts WHERE association_groups != jsonb_build_array(
                jsonb_build_object('agency_id', agency_id::text, 'group_id', group_id::text)))
    """)).scalar_one()
    if retained:
        raise RuntimeError("MCP workflow history must be retained; roll back application code with the additive schema in place.")
    op.drop_table("mcp_record_revisions")
    op.drop_table("mcp_artifact_access")
    op.drop_column("mcp_artifacts", "association_groups")
