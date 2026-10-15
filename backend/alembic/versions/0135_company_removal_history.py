"""Retain revoked manager assignments when a client is removed.

No source rows are changed. Independent tenant FKs preserve the boundary when
the old company reference is detached from a revoked assignment.
"""
import sqlalchemy as sa
from alembic import op

revision = "0135_company_removal_history"
down_revision = "0134_company_data_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '90s'")
    op.create_foreign_key("fk_client_manager_assignment_retained_profile",
        "client_manager_group_assignments", "client_manager_profiles",
        ["profile_id", "agency_id"], ["id", "agency_id"], ondelete="CASCADE")
    op.create_foreign_key("fk_client_manager_assignment_retained_group",
        "client_manager_group_assignments", "gc_group_access",
        ["gc_group_access_id", "agency_id", "group_id"], ["id", "agency_id", "group_id"],
        ondelete="CASCADE")
    op.create_check_constraint("ck_client_manager_assignment_active_organization",
        "client_manager_group_assignments", "NOT is_active OR organization_id IS NOT NULL")
    op.alter_column("client_manager_group_assignments", "organization_id",
        existing_type=sa.UUID(), nullable=True)
    op.create_index("ix_client_manager_assignment_company", "client_manager_group_assignments",
        ["agency_id", "organization_id", "id"])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM client_manager_group_assignments WHERE organization_id IS NULL)")):
        raise RuntimeError("Retained company-removal history exists; refuse to discard it.")
    op.alter_column("client_manager_group_assignments", "organization_id", existing_type=sa.UUID(), nullable=False)
    op.drop_index("ix_client_manager_assignment_company", table_name="client_manager_group_assignments")
    op.drop_constraint("ck_client_manager_assignment_active_organization", "client_manager_group_assignments")
    op.drop_constraint("fk_client_manager_assignment_retained_group", "client_manager_group_assignments", type_="foreignkey")
    op.drop_constraint("fk_client_manager_assignment_retained_profile", "client_manager_group_assignments", type_="foreignkey")
