"""Bind mobile passenger identities and document cache rows to one tenant/group.

Revision ID: 0071_mobile_scope_constraints
Revises: 0070_mobile_ops_indexes
"""

from __future__ import annotations

from alembic import op

revision = "0071_mobile_scope_constraints"
down_revision = "0070_mobile_ops_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Refuse to install ownership constraints over inconsistent historical
    # rows. The deployment remains unchanged and requires explicit data review
    # instead of silently reassigning or deleting passenger data.
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
              FROM mobile_passenger_identities identity
              JOIN passport_submissions submission
                ON submission.id = identity.passenger_submission_id
             WHERE submission.agency_id <> identity.agency_id
                OR submission.group_id <> identity.group_id
          ) THEN
            RAISE EXCEPTION 'mobile passenger identity scope mismatch';
          END IF;
          IF EXISTS (
            SELECT 1
              FROM mobile_document_metadata_cache document
              JOIN mobile_passenger_identities identity
                ON identity.id = document.passenger_identity_id
             WHERE identity.gc_group_access_id <> document.gc_group_access_id
                OR identity.agency_id <> document.agency_id
                OR identity.group_id <> document.group_id
                OR identity.passenger_submission_id <> document.passenger_submission_id
          ) THEN
            RAISE EXCEPTION 'mobile document passenger scope mismatch';
          END IF;
        END $$;
        """
    )
    # Build supporting unique indexes without blocking the populated source
    # tables, then attach them as constraints with only a short metadata lock.
    with op.get_context().autocommit_block():
        op.create_index(
            "uq_passport_submissions_mobile_scope",
            "passport_submissions",
            ["id", "agency_id", "group_id"],
            unique=True,
            postgresql_concurrently=True,
        )
    op.execute(
        """
        ALTER TABLE passport_submissions
        ADD CONSTRAINT uq_passport_submissions_mobile_scope
        UNIQUE USING INDEX uq_passport_submissions_mobile_scope
        """
    )
    op.drop_constraint(
        "mobile_passenger_identities_passenger_submission_id_fkey",
        "mobile_passenger_identities",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_mobile_passenger_identity_submission_scope",
        "mobile_passenger_identities",
        "passport_submissions",
        ["passenger_submission_id", "agency_id", "group_id"],
        ["id", "agency_id", "group_id"],
        ondelete="CASCADE",
        postgresql_not_valid=True,
    )
    op.execute(
        """
        ALTER TABLE mobile_passenger_identities
        VALIDATE CONSTRAINT fk_mobile_passenger_identity_submission_scope
        """
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "uq_mobile_passenger_identity_document_scope",
            "mobile_passenger_identities",
            ["id", "gc_group_access_id", "agency_id", "group_id", "passenger_submission_id"],
            unique=True,
            postgresql_concurrently=True,
        )
    op.execute(
        """
        ALTER TABLE mobile_passenger_identities
        ADD CONSTRAINT uq_mobile_passenger_identity_document_scope
        UNIQUE USING INDEX uq_mobile_passenger_identity_document_scope
        """
    )
    op.drop_constraint(
        "fk_mobile_document_cache_identity",
        "mobile_document_metadata_cache",
        type_="foreignkey",
    )
    op.drop_constraint(
        "mobile_document_metadata_cache_passenger_submission_id_fkey",
        "mobile_document_metadata_cache",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_mobile_document_cache_identity",
        "mobile_document_metadata_cache",
        "mobile_passenger_identities",
        [
            "passenger_identity_id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            "passenger_submission_id",
        ],
        ["id", "gc_group_access_id", "agency_id", "group_id", "passenger_submission_id"],
        ondelete="CASCADE",
        postgresql_not_valid=True,
    )
    op.execute(
        """
        ALTER TABLE mobile_document_metadata_cache
        VALIDATE CONSTRAINT fk_mobile_document_cache_identity
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_mobile_document_cache_identity",
        "mobile_document_metadata_cache",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_mobile_document_cache_identity",
        "mobile_document_metadata_cache",
        "mobile_passenger_identities",
        ["passenger_identity_id", "gc_group_access_id", "agency_id", "group_id"],
        ["id", "gc_group_access_id", "agency_id", "group_id"],
        ondelete="CASCADE",
        postgresql_not_valid=True,
    )
    op.execute(
        """
        ALTER TABLE mobile_document_metadata_cache
        VALIDATE CONSTRAINT fk_mobile_document_cache_identity
        """
    )
    op.create_foreign_key(
        "mobile_document_metadata_cache_passenger_submission_id_fkey",
        "mobile_document_metadata_cache",
        "passport_submissions",
        ["passenger_submission_id"],
        ["id"],
        ondelete="CASCADE",
        postgresql_not_valid=True,
    )
    op.execute(
        """
        ALTER TABLE mobile_document_metadata_cache
        VALIDATE CONSTRAINT mobile_document_metadata_cache_passenger_submission_id_fkey
        """
    )
    op.drop_constraint(
        "uq_mobile_passenger_identity_document_scope",
        "mobile_passenger_identities",
        type_="unique",
    )
    op.drop_constraint(
        "fk_mobile_passenger_identity_submission_scope",
        "mobile_passenger_identities",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "mobile_passenger_identities_passenger_submission_id_fkey",
        "mobile_passenger_identities",
        "passport_submissions",
        ["passenger_submission_id"],
        ["id"],
        ondelete="CASCADE",
        postgresql_not_valid=True,
    )
    op.execute(
        """
        ALTER TABLE mobile_passenger_identities
        VALIDATE CONSTRAINT mobile_passenger_identities_passenger_submission_id_fkey
        """
    )
    op.drop_constraint(
        "uq_passport_submissions_mobile_scope",
        "passport_submissions",
        type_="unique",
    )
