"""Keep exact traveller phone corrections local to a WhatsApp broadcast.

Revision ID: 0105_whatsapp_phone_overrides
Revises: 0104_whatsapp_source_contacts
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0105_whatsapp_phone_overrides"
down_revision = "0104_whatsapp_source_contacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whatsapp_broadcast_recipients", sa.Column(
        "merged_into_recipient_id", postgresql.UUID(as_uuid=True), nullable=True,
    ))
    op.add_column("whatsapp_broadcast_recipients", sa.Column(
        "merged_contacts", postgresql.JSONB(), nullable=False, server_default="[]",
    ))
    op.create_foreign_key(
        "fk_whatsapp_recipient_merge_target", "whatsapp_broadcast_recipients",
        "whatsapp_broadcast_recipients", ["merged_into_recipient_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        "ix_whatsapp_broadcast_recipients_merged_into_recipient_id",
        "whatsapp_broadcast_recipients", ["merged_into_recipient_id"],
    )
    op.create_table(
        "whatsapp_traveller_phone_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("broadcast_group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("whatsapp_broadcast_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("client_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("passenger_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("passport_submissions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("whatsapp_broadcast_recipients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_phone_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("broadcast_group_id", "passenger_id", name="uq_whatsapp_phone_override_passenger"),
    )
    op.create_index("ix_whatsapp_phone_overrides_agency_group", "whatsapp_traveller_phone_overrides", ["agency_id", "group_id"])
    op.create_index("ix_whatsapp_phone_overrides_recipient", "whatsapp_traveller_phone_overrides", ["recipient_id"])


def downgrade() -> None:
    op.drop_table("whatsapp_traveller_phone_overrides")
    op.drop_index("ix_whatsapp_broadcast_recipients_merged_into_recipient_id", table_name="whatsapp_broadcast_recipients")
    op.drop_constraint("fk_whatsapp_recipient_merge_target", "whatsapp_broadcast_recipients", type_="foreignkey")
    op.drop_column("whatsapp_broadcast_recipients", "merged_into_recipient_id")
    op.drop_column("whatsapp_broadcast_recipients", "merged_contacts")
