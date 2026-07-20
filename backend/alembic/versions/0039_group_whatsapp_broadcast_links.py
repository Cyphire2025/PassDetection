"""Link client groups to existing WhatsApp broadcast groups.

Revision ID: 0039_group_whatsapp_links
Revises: 0038_whatsapp_resend
Create Date: 2026-07-20
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0039_group_whatsapp_links"
down_revision = "0038_whatsapp_resend"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_group_whatsapp_broadcast_links",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "client_group_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "broadcast_group_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "agency_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["broadcast_group_id"],
            ["whatsapp_broadcast_groups.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["client_group_id"],
            ["client_groups.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "client_group_id",
            "broadcast_group_id",
            name="uq_client_group_whatsapp_broadcast_link",
        ),
    )
    op.create_index(
        "ix_client_group_whatsapp_broadcast_links_client_group_id",
        "client_group_whatsapp_broadcast_links",
        ["client_group_id"],
    )
    op.create_index(
        "ix_client_group_whatsapp_broadcast_links_broadcast_group_id",
        "client_group_whatsapp_broadcast_links",
        ["broadcast_group_id"],
    )
    op.create_index(
        "ix_client_group_whatsapp_broadcast_links_agency_id",
        "client_group_whatsapp_broadcast_links",
        ["agency_id"],
    )
    op.create_index(
        "ix_client_group_whatsapp_broadcast_links_created_by_user_id",
        "client_group_whatsapp_broadcast_links",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_client_group_whatsapp_links_agency_group",
        "client_group_whatsapp_broadcast_links",
        ["agency_id", "client_group_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_client_group_whatsapp_links_agency_group",
        table_name="client_group_whatsapp_broadcast_links",
    )
    op.drop_index(
        "ix_client_group_whatsapp_broadcast_links_created_by_user_id",
        table_name="client_group_whatsapp_broadcast_links",
    )
    op.drop_index(
        "ix_client_group_whatsapp_broadcast_links_agency_id",
        table_name="client_group_whatsapp_broadcast_links",
    )
    op.drop_index(
        "ix_client_group_whatsapp_broadcast_links_broadcast_group_id",
        table_name="client_group_whatsapp_broadcast_links",
    )
    op.drop_index(
        "ix_client_group_whatsapp_broadcast_links_client_group_id",
        table_name="client_group_whatsapp_broadcast_links",
    )
    op.drop_table("client_group_whatsapp_broadcast_links")
