"""Configurable WhatsApp roster matching fields.

Revision ID: 0092_whatsapp_matching_fields
Revises: 0091_qualifier_other_relation
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0092_whatsapp_matching_fields"
down_revision = "0091_qualifier_other_relation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_broadcast_groups",
        sa.Column(
            "imported_field_keys",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "client_group_whatsapp_broadcast_links",
        sa.Column("matching_field_keys", postgresql.JSONB(), nullable=True),
    )
    # Backfill canonical keys for lists created before this feature, excluding
    # internal provenance. Legacy null/non-object JSON must not abort upgrades.
    op.execute(
        """
        UPDATE whatsapp_broadcast_groups AS groups
        SET imported_field_keys = COALESCE(
            (
                SELECT jsonb_agg(keys.key ORDER BY keys.key)
                FROM (
                    SELECT DISTINCT recipient_keys.key
                    FROM whatsapp_broadcast_recipients AS recipients
                    CROSS JOIN LATERAL jsonb_object_keys(
                        CASE WHEN jsonb_typeof(recipients.imported_fields) = 'object'
                            THEN recipients.imported_fields ELSE '{}'::jsonb END
                    ) AS recipient_keys(key)
                    WHERE recipients.broadcast_group_id = groups.id
                      AND recipient_keys.key NOT IN (
                          'source_file', 'source_order', 'source_sheet',
                          'source_row', 'duplicate_conflicting_fields'
                      )
                      AND NOT (
                          recipient_keys.key ~ '_[0-9]+$'
                          AND regexp_replace(
                              recipient_keys.key, '_[0-9]+$', ''
                          ) = ANY(regexp_split_to_array(
                              COALESCE(
                                  recipients.imported_fields
                                      ->> 'duplicate_conflicting_fields',
                                  ''
                              ),
                              '[[:space:]]*,[[:space:]]*'
                          ))
                      )
                    UNION
                    SELECT DISTINCT rejected_keys.key
                    FROM whatsapp_broadcast_rejected_contacts AS rejected
                    CROSS JOIN LATERAL jsonb_object_keys(
                        CASE WHEN jsonb_typeof(rejected.imported_fields) = 'object'
                            THEN rejected.imported_fields ELSE '{}'::jsonb END
                    ) AS rejected_keys(key)
                    WHERE rejected.broadcast_group_id = groups.id
                      AND rejected_keys.key NOT IN (
                          'source_file', 'source_order', 'source_sheet',
                          'source_row', 'duplicate_conflicting_fields'
                      )
                      AND NOT (
                          rejected_keys.key ~ '_[0-9]+$'
                          AND regexp_replace(
                              rejected_keys.key, '_[0-9]+$', ''
                          ) = ANY(regexp_split_to_array(
                              COALESCE(
                                  rejected.imported_fields
                                      ->> 'duplicate_conflicting_fields',
                                  ''
                              ),
                              '[[:space:]]*,[[:space:]]*'
                          ))
                      )
                ) AS keys
            ),
            '[]'::jsonb
        )
        """
    )


def downgrade() -> None:
    op.drop_column(
        "client_group_whatsapp_broadcast_links",
        "matching_field_keys",
    )
    op.drop_column("whatsapp_broadcast_groups", "imported_field_keys")
