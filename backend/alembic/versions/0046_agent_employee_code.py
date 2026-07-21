"""Add Agent/Employee code option to client groups.

Revision ID: 0046_agent_employee_code
Revises: 0045_document_whatsapp
Create Date: 2026-07-22
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0046_agent_employee_code"
down_revision = "0045_document_whatsapp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_groups",
        sa.Column(
            "agent_employee_code_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("client_groups", "agent_employee_code_enabled")
