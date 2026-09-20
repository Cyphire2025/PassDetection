"""Retain source travellers separately from unique WhatsApp delivery numbers.

Revision ID: 0104_whatsapp_source_contacts
Revises: 0103_whatsapp_template_language
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0104_whatsapp_source_contacts"
down_revision = "0103_whatsapp_template_language"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("client_group_whatsapp_broadcast_links", sa.Column(
        "sync_contacts_from_group", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.add_column("whatsapp_broadcast_recipients", sa.Column(
        "is_source_managed", sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.create_table(
        "whatsapp_broadcast_source_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("broadcast_group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_submission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("passport_submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("whatsapp_broadcast_recipients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("raw_phone_number", sa.Text(), nullable=True),
        sa.Column("normalized_phone_number", sa.String(32), nullable=True),
        sa.Column("issue", sa.String(32), nullable=True),
        sa.Column("imported_fields", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("broadcast_group_id", "source_group_id", "source_submission_id", name="uq_whatsapp_source_contact_submission"),
    )
    op.create_index("ix_whatsapp_source_contacts_agency_source", "whatsapp_broadcast_source_contacts", ["agency_id", "source_group_id"])
    op.create_index("ix_whatsapp_source_contacts_broadcast", "whatsapp_broadcast_source_contacts", ["broadcast_group_id"])
    op.create_index("ix_whatsapp_source_contacts_recipient", "whatsapp_broadcast_source_contacts", ["recipient_id"])
    op.create_index("ix_whatsapp_source_contacts_submission", "whatsapp_broadcast_source_contacts", ["source_submission_id"])
    # Existing import-only links become one-way sources. Backfill their contact
    # snapshots with the deployment CLI after this schema migration commits.
    op.execute(sa.text("""
        UPDATE client_group_whatsapp_broadcast_links AS link
        SET sync_contacts_from_group = true
        FROM client_groups AS source
        WHERE source.id = link.client_group_id
          AND source.agency_id = link.agency_id AND source.import_only = true
    """))


def downgrade() -> None:
    op.drop_table("whatsapp_broadcast_source_contacts")
    op.drop_column("whatsapp_broadcast_recipients", "is_source_managed")
    op.drop_column("client_group_whatsapp_broadcast_links", "sync_contacts_from_group")
