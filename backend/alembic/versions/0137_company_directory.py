"""Add rebuildable encrypted company directory indexes; no source data changes."""

import sqlalchemy as sa
from alembic import op

revision = "0137_company_directory"
down_revision = "0136_returning_drafts"
branch_labels = None
depends_on = None


def _scope() -> list[sa.Column]:
    return [sa.Column("agency_id", sa.UUID(), nullable=False), sa.Column("company_id", sa.UUID(), nullable=False)]


def _person_scope(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["traveller_id", "agency_id", "company_id"],
        ["traveller_profiles.id", "traveller_profiles.agency_id", "traveller_profiles.company_id"],
        name=f"fk_{name}_traveller_scope", ondelete="RESTRICT")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '90s'")
    op.create_table("company_directory_states", sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("backfill_after", sa.UUID()), sa.Column("backfill_complete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["company_id", "agency_id"], ["client_organizations.id", "client_organizations.agency_id"],
            name="fk_company_directory_state_company_scope", ondelete="RESTRICT"))
    op.create_index("ix_company_directory_backfill", "company_directory_states", ["backfill_complete", "company_id"])
    op.create_table("company_directory_people", *_scope(), sa.Column("traveller_id", sa.UUID(), primary_key=True),
        sa.Column("name_ciphertext", sa.Text(), nullable=False), sa.Column("name_rank", sa.String(78), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False), sa.Column("key_version", sa.String(32), nullable=False),
        sa.Column("submission_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latest_submission_at", sa.DateTime(timezone=True)), sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_sort_at", sa.DateTime(timezone=True), nullable=False),
        _person_scope("company_directory_person"),
        sa.CheckConstraint("submission_count >= 0 AND profile_revision >= 1", name="ck_company_directory_counts"),
        sa.CheckConstraint("length(name_rank) = 78", name="ck_company_directory_rank"))
    op.create_index("ix_company_directory_name", "company_directory_people", ["agency_id", "company_id", "name_rank", "traveller_id"], unique=True)
    op.create_index("ix_company_directory_latest", "company_directory_people", ["agency_id", "company_id", "latest_sort_at", "traveller_id"])
    op.create_index("ix_company_directory_count_name", "company_directory_people", ["agency_id", "company_id", "submission_count", "name_rank", "traveller_id"])
    op.create_table("company_directory_prefixes", *_scope(), sa.Column("traveller_id", sa.UUID(), primary_key=True),
        sa.Column("token_digest", sa.LargeBinary(32), primary_key=True), sa.Column("key_version", sa.String(32), nullable=False),
        _person_scope("company_directory_prefix"))
    op.create_index("ix_company_directory_prefix_seek", "company_directory_prefixes", ["agency_id", "company_id", "key_version", "token_digest", "traveller_id"])
    op.create_table("company_directory_group_counts", *_scope(), sa.Column("traveller_id", sa.UUID(), primary_key=True),
        sa.Column("group_id", sa.UUID(), primary_key=True), sa.Column("submission_count", sa.Integer(), nullable=False),
        sa.Column("latest_submission_at", sa.DateTime(timezone=True), nullable=False), _person_scope("company_directory_group_count"),
        sa.ForeignKeyConstraint(["group_id", "agency_id"], ["client_groups.id", "client_groups.agency_id"], name="fk_company_directory_group_count_group_scope", ondelete="RESTRICT"),
        sa.CheckConstraint("submission_count >= 1", name="ck_company_directory_group_count"))
    op.create_index("ix_company_directory_group_scope", "company_directory_group_counts", ["agency_id", "company_id", "group_id", "traveller_id"])
    op.create_table("company_directory_queue", *_scope(), sa.Column("traveller_id", sa.UUID(), primary_key=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("last_error_code", sa.String(32)),
        _person_scope("company_directory_queue"))
    op.create_index("ix_company_directory_queue_ready", "company_directory_queue", ["available_at", "traveller_id"])
    op.create_index("ix_company_directory_queue_company", "company_directory_queue", ["agency_id", "company_id", "traveller_id"])


def downgrade() -> None:
    # Only derived indexes are removed. Authoritative travellers and sources stay.
    for table in ("company_directory_queue", "company_directory_group_counts", "company_directory_prefixes",
        "company_directory_people", "company_directory_states"):
        op.drop_table(table)
