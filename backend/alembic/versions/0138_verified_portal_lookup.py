"""Add private number-only lookup and accurately labelled proof-only grants.

Existing passport data and historical actor evidence are unchanged. A bounded
operator backfill derives the new keyed lookup before the portal is enabled.
"""
import sqlalchemy as sa
from alembic import op

revision = "0138_verified_portal_lookup"
down_revision = "0137_company_directory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("SET LOCAL statement_timeout = '90s'")
    op.add_column("traveller_passports", sa.Column("number_lookup_fingerprint", sa.String(64), nullable=True))
    op.create_index("ix_traveller_passport_number_lookup", "traveller_passports",
        ["agency_id", "company_id", "fingerprint_key_version", "number_lookup_fingerprint"])
    for table, name in (("traveller_claims", "ck_traveller_claim_actor"),
                        ("traveller_history_grants", "ck_traveller_grant_actor")):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, "actor_kind IN ('self','delegate','guardian','verified')")


def downgrade() -> None:
    for table in ("traveller_claims", "traveller_history_grants"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE actor_kind = 'verified')")):
            raise RuntimeError("Verified access history exists; refuse to relabel or discard it.")
    for table, name in (("traveller_claims", "ck_traveller_claim_actor"),
                        ("traveller_history_grants", "ck_traveller_grant_actor")):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, "actor_kind IN ('self','delegate','guardian')")
    op.drop_index("ix_traveller_passport_number_lookup", table_name="traveller_passports")
    op.drop_column("traveller_passports", "number_lookup_fingerprint")
