"""Update the persisted default platform brand.

Revision ID: 0041_global_connects_brand
Revises: 0040_whatsapp_recipient_fields
Create Date: 2026-07-20
"""

from __future__ import annotations

from alembic import op

revision = "0041_global_connects_brand"
down_revision = "0040_whatsapp_recipient_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Rename only installations still using the former default."""

    op.execute(
        """
        UPDATE platform_settings
        SET value = jsonb_set(
            value,
            '{platform_name}',
            '"Global Connects Dashboard"'::jsonb,
            true
        )
        WHERE key = 'global'
          AND value ->> 'platform_name' = 'PassDetection'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE platform_settings
        SET value = jsonb_set(
            value,
            '{platform_name}',
            '"PassDetection"'::jsonb,
            true
        )
        WHERE key = 'global'
          AND value ->> 'platform_name' = 'Global Connects Dashboard'
        """
    )
