"""Add Group Companion mobile persistence foundation.

Revision ID: 0069_gc_mobile_foundation
Revises: 0068_document_chunk_limits

All mobile access is opt-in. This migration creates no enabled group,
passenger identity, client-manager assignment, session, or delegation.
Sensitive credentials are represented only by hashes or application-encrypted
ciphertext.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0069_gc_mobile_foundation"
down_revision = "0068_document_chunk_limits"
branch_labels = None
depends_on = None


_TABLES_IN_DEPENDENCY_ORDER = (
    "client_organizations",
    "client_manager_profiles",
    "gc_group_access",
    "client_manager_group_assignments",
    "gc_common_documents",
    "gc_itinerary_versions",
    "gc_itinerary_days",
    "gc_itinerary_items",
    "gc_announcements",
    "mobile_passenger_identities",
    "mobile_document_metadata_cache",
    "mobile_otp_challenges",
    "mobile_device_sessions",
    "mobile_refresh_tokens",
    "mobile_push_registrations",
    "mobile_notifications",
    "mobile_sync_changes",
    "passenger_family_delegations",
    "mobile_idempotency_receipts",
    "mobile_incidents",
)


def upgrade() -> None:
    # PostgreSQL cannot safely add enum members inside a transaction that then
    # immediately uses the value. The role is intentionally not granted or
    # backfilled here.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role_enum ADD VALUE IF NOT EXISTS 'client_manager'")

    op.create_table(
        "client_organizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("external_reference", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("updated_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(status = 'deleted' AND deleted_at IS NOT NULL) OR (status != 'deleted' AND deleted_at IS NULL)",
            name="ck_client_org_deleted_shape",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive', 'deleted')", name="ck_client_org_status"
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "agency_id", name="uq_client_org_id_agency"),
    )
    op.create_index(
        "ix_client_org_agency_status", "client_organizations", ["agency_id", "status"], unique=False
    )
    op.create_index(
        "uq_client_org_agency_external_ref",
        "client_organizations",
        ["agency_id", "external_reference"],
        unique=True,
        postgresql_where=sa.text("external_reference IS NOT NULL"),
        sqlite_where=sa.text("external_reference IS NOT NULL"),
    )
    op.create_index(
        "uq_client_org_agency_name_live",
        "client_organizations",
        ["agency_id", "normalized_name"],
        unique=True,
        postgresql_where=sa.text("status != 'deleted'"),
        sqlite_where=sa.text("status != 'deleted'"),
    )
    op.create_table(
        "client_manager_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("normalized_phone_number", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="invited", nullable=False),
        sa.Column("force_password_change", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("invitation_token_hash", sa.String(length=64), nullable=True),
        sa.Column("invitation_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("updated_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'active' AND activated_at IS NOT NULL AND suspended_at IS NULL AND deleted_at IS NULL) OR (status = 'invited' AND activated_at IS NULL AND suspended_at IS NULL AND deleted_at IS NULL) OR (status = 'suspended' AND suspended_at IS NOT NULL AND deleted_at IS NULL) OR (status = 'deleted' AND deleted_at IS NOT NULL)",
            name="ck_client_manager_profile_state_shape",
        ),
        sa.CheckConstraint(
            "length(normalized_phone_number) BETWEEN 9 AND 16 AND normalized_phone_number LIKE '+%'",
            name="ck_client_manager_profile_phone",
        ),
        sa.CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'deleted')",
            name="ck_client_manager_profile_status",
        ),
        sa.CheckConstraint(
            "(invitation_token_hash IS NULL) = (invitation_expires_at IS NULL)",
            name="ck_client_manager_profile_invitation_pair",
        ),
        sa.CheckConstraint("access_generation >= 0", name="ck_client_manager_profile_generation"),
        sa.CheckConstraint("revision >= 1", name="ck_client_manager_profile_revision"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["organization_id", "agency_id"],
            ["client_organizations.id", "client_organizations.agency_id"],
            name="fk_client_manager_profile_org",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "agency_id", "organization_id", name="uq_client_manager_profile_org"
        ),
        sa.UniqueConstraint("id", "agency_id", name="uq_client_manager_profile_agency"),
        sa.UniqueConstraint("user_id", name="uq_client_manager_profile_user"),
    )
    op.create_index(
        "ix_client_manager_org_status",
        "client_manager_profiles",
        ["organization_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_client_manager_phone_live",
        "client_manager_profiles",
        ["agency_id", "normalized_phone_number"],
        unique=True,
        postgresql_where=sa.text("status != 'deleted'"),
        sqlite_where=sa.text("status != 'deleted'"),
    )
    op.create_table(
        "gc_group_access",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("client_organization_id", sa.UUID(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("passenger_access_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "client_manager_access_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column(
            "coordinator_access_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("access_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.UUID(), nullable=True),
        sa.Column("access_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("manifest_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("itinerary_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("common_document_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("announcement_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("rooming_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("meal_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("qr_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("updated_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "NOT client_manager_access_enabled OR client_organization_id IS NOT NULL",
            name="ck_gc_group_access_manager_org",
        ),
        sa.CheckConstraint(
            "access_expires_at IS NULL OR access_starts_at IS NULL OR access_expires_at > access_starts_at",
            name="ck_gc_group_access_window",
        ),
        sa.CheckConstraint("access_generation >= 0", name="ck_gc_group_access_generation"),
        sa.CheckConstraint(
            "manifest_version >= 0 AND itinerary_version >= 0 AND common_document_version >= 0 AND announcement_version >= 0 AND rooming_version >= 0 AND meal_version >= 0 AND qr_version >= 0",
            name="ck_gc_group_access_versions",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_gc_group_access_revision"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["client_organization_id", "agency_id"],
            ["client_organizations.id", "client_organizations.agency_id"],
            name="fk_gc_group_access_org",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", name="uq_gc_group_access_group"),
        sa.UniqueConstraint(
            "id",
            "agency_id",
            "group_id",
            "client_organization_id",
            name="uq_gc_group_access_org_scope",
        ),
        sa.UniqueConstraint("id", "agency_id", "group_id", name="uq_gc_group_access_scope"),
    )
    op.create_index(
        "ix_gc_group_access_agency_enabled",
        "gc_group_access",
        ["agency_id", "is_enabled"],
        unique=False,
    )
    op.create_index(
        "ix_gc_group_access_window",
        "gc_group_access",
        ["access_starts_at", "access_expires_at"],
        unique=False,
    )
    op.create_table(
        "client_manager_group_assignments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("can_view_passenger_names", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "personal_document_access_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("assigned_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("revoked_by_user_id", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(is_active AND revoked_at IS NULL AND revoked_by_user_id IS NULL) OR (NOT is_active AND revoked_at IS NOT NULL)",
            name="ck_client_manager_assignment_state",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id", "organization_id"],
            [
                "gc_group_access.id",
                "gc_group_access.agency_id",
                "gc_group_access.group_id",
                "gc_group_access.client_organization_id",
            ],
            name="fk_client_manager_assignment_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "agency_id", "organization_id"],
            [
                "client_manager_profiles.id",
                "client_manager_profiles.agency_id",
                "client_manager_profiles.organization_id",
            ],
            name="fk_client_manager_assignment_profile",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id", "gc_group_access_id", name="uq_client_manager_group_assignment"
        ),
    )
    op.create_index(
        "ix_client_manager_assignment_group",
        "client_manager_group_assignments",
        ["gc_group_access_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_client_manager_assignment_profile",
        "client_manager_group_assignments",
        ["profile_id", "is_active"],
        unique=False,
    )
    op.create_table(
        "gc_common_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=False),
        sa.Column("logical_document_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("safe_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("passenger_visible", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("client_manager_visible", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("coordinator_visible", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("offline_available", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("availability_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("availability_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_user_id", sa.UUID(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) OR (status IN ('published', 'retired', 'revoked') AND published_at IS NOT NULL)",
            name="ck_gc_common_doc_publish_shape",
        ),
        sa.CheckConstraint(
            "category IN ('itinerary_pdf', 'travel_tips', 'common_instructions', 'destination', 'emergency', 'hotel', 'flight_summary', 'meeting_point', 'dress_code', 'baggage', 'other')",
            name="ck_gc_common_doc_category",
        ),
        sa.CheckConstraint(
            "status != 'published' OR (passenger_visible OR client_manager_visible OR coordinator_visible)",
            name="ck_gc_common_doc_audience",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired', 'revoked')", name="ck_gc_common_doc_status"
        ),
        sa.CheckConstraint(
            "availability_expires_at IS NULL OR availability_starts_at IS NULL OR availability_expires_at > availability_starts_at",
            name="ck_gc_common_doc_window",
        ),
        sa.CheckConstraint("byte_size > 0", name="ck_gc_common_doc_size"),
        sa.CheckConstraint("length(checksum_sha256) = 64", name="ck_gc_common_doc_checksum"),
        sa.CheckConstraint("version >= 1", name="ck_gc_common_doc_version"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_gc_common_doc_access",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gc_group_access_id",
            "logical_document_id",
            "version",
            name="uq_gc_common_doc_logical_version",
        ),
        sa.UniqueConstraint(
            "id", "gc_group_access_id", "agency_id", "group_id", name="uq_gc_common_doc_scope"
        ),
        sa.UniqueConstraint("storage_key", name="uq_gc_common_doc_storage_key"),
    )
    op.create_index(
        "ix_gc_common_doc_manifest",
        "gc_common_documents",
        ["gc_group_access_id", "status", "sort_order"],
        unique=False,
    )
    op.create_index(
        "uq_gc_common_doc_published",
        "gc_common_documents",
        ["gc_group_access_id", "logical_document_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
        sqlite_where=sa.text("status = 'published'"),
    )
    op.create_table(
        "gc_itinerary_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("destination_information", sa.Text(), nullable=True),
        sa.Column("content_checksum", sa.String(length=64), nullable=True),
        sa.Column("availability_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("availability_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) OR (status IN ('published', 'retired') AND published_at IS NOT NULL)",
            name="ck_gc_itinerary_publish_shape",
        ),
        sa.CheckConstraint(
            "status = 'draft' OR content_checksum IS NOT NULL",
            name="ck_gc_itinerary_published_checksum",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired')", name="ck_gc_itinerary_version_status"
        ),
        sa.CheckConstraint(
            "availability_expires_at IS NULL OR availability_starts_at IS NULL OR availability_expires_at > availability_starts_at",
            name="ck_gc_itinerary_version_window",
        ),
        sa.CheckConstraint(
            "content_checksum IS NULL OR length(content_checksum) = 64",
            name="ck_gc_itinerary_checksum",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_gc_itinerary_version_revision"),
        sa.CheckConstraint("version >= 1", name="ck_gc_itinerary_version_number"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_gc_itinerary_version_access",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("gc_group_access_id", "version", name="uq_gc_itinerary_version_number"),
        sa.UniqueConstraint(
            "id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            name="uq_gc_itinerary_version_scope",
        ),
    )
    op.create_index(
        "ix_gc_itinerary_access_status",
        "gc_itinerary_versions",
        ["gc_group_access_id", "status", "version"],
        unique=False,
    )
    op.create_index(
        "uq_gc_itinerary_published",
        "gc_itinerary_versions",
        ["gc_group_access_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
        sqlite_where=sa.text("status = 'published'"),
    )
    op.create_table(
        "gc_itinerary_days",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=False),
        sa.Column("itinerary_version_id", sa.UUID(), nullable=False),
        sa.Column("day_number", sa.Integer(), nullable=False),
        sa.Column("trip_date", sa.Date(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("day_number >= 1", name="ck_gc_itinerary_day_number"),
        sa.CheckConstraint("sort_order >= 0", name="ck_gc_itinerary_day_sort"),
        sa.ForeignKeyConstraint(
            ["itinerary_version_id", "gc_group_access_id", "agency_id", "group_id"],
            [
                "gc_itinerary_versions.id",
                "gc_itinerary_versions.gc_group_access_id",
                "gc_itinerary_versions.agency_id",
                "gc_itinerary_versions.group_id",
            ],
            name="fk_gc_itinerary_day_version",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "itinerary_version_id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            name="uq_gc_itinerary_day_scope",
        ),
        sa.UniqueConstraint(
            "itinerary_version_id", "day_number", name="uq_gc_itinerary_day_number"
        ),
    )
    op.create_index(
        "ix_gc_itinerary_day_order",
        "gc_itinerary_days",
        ["itinerary_version_id", "sort_order", "day_number"],
        unique=False,
    )
    op.create_table(
        "gc_itinerary_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=False),
        sa.Column("itinerary_version_id", sa.UUID(), nullable=False),
        sa.Column("itinerary_day_id", sa.UUID(), nullable=False),
        sa.Column("common_document_id", sa.UUID(), nullable=True),
        sa.Column("item_type", sa.String(length=24), server_default="activity", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_all_day", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("location_name", sa.String(length=255), nullable=True),
        sa.Column("location_address", sa.String(length=1000), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("map_uri", sa.String(length=2048), nullable=True),
        sa.Column("contact_name", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=32), nullable=True),
        sa.Column("is_important", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "public_metadata",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "item_type IN ('travel', 'flight', 'transfer', 'hotel', 'meal', 'meeting', 'activity', 'conference', 'free_time', 'instruction', 'other')",
            name="ck_gc_itinerary_item_type",
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at",
            name="ck_gc_itinerary_item_window",
        ),
        sa.CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="ck_gc_itinerary_item_latitude",
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="ck_gc_itinerary_item_longitude",
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_gc_itinerary_item_sort"),
        sa.ForeignKeyConstraint(
            ["common_document_id", "gc_group_access_id", "agency_id", "group_id"],
            [
                "gc_common_documents.id",
                "gc_common_documents.gc_group_access_id",
                "gc_common_documents.agency_id",
                "gc_common_documents.group_id",
            ],
            name="fk_gc_itinerary_item_document",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "itinerary_day_id",
                "itinerary_version_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
            ],
            [
                "gc_itinerary_days.id",
                "gc_itinerary_days.itinerary_version_id",
                "gc_itinerary_days.gc_group_access_id",
                "gc_itinerary_days.agency_id",
                "gc_itinerary_days.group_id",
            ],
            name="fk_gc_itinerary_item_day",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_gc_itinerary_item_order",
        "gc_itinerary_items",
        ["itinerary_day_id", "sort_order"],
        unique=False,
    )
    op.create_table(
        "gc_announcements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=False),
        sa.Column("logical_announcement_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=24), server_default="general", nullable=False),
        sa.Column("priority", sa.String(length=16), server_default="normal", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("deep_link_path", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="draft", nullable=False),
        sa.Column("passenger_visible", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("client_manager_visible", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("coordinator_visible", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("offline_available", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("availability_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("availability_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_user_id", sa.UUID(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND published_at IS NULL) OR (status IN ('published', 'retired', 'revoked') AND published_at IS NOT NULL)",
            name="ck_gc_announcement_publish_shape",
        ),
        sa.CheckConstraint(
            "category IN ('general', 'itinerary', 'room', 'flight', 'document', 'coordinator', 'emergency', 'sync')",
            name="ck_gc_announcement_category",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'emergency')", name="ck_gc_announcement_priority"
        ),
        sa.CheckConstraint(
            "status != 'published' OR (passenger_visible OR client_manager_visible OR coordinator_visible)",
            name="ck_gc_announcement_audience",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retired', 'revoked')",
            name="ck_gc_announcement_status",
        ),
        sa.CheckConstraint(
            "availability_expires_at IS NULL OR availability_starts_at IS NULL OR availability_expires_at > availability_starts_at",
            name="ck_gc_announcement_window",
        ),
        sa.CheckConstraint("version >= 1", name="ck_gc_announcement_version"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_gc_announcement_access",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gc_group_access_id",
            "logical_announcement_id",
            "version",
            name="uq_gc_announcement_logical_version",
        ),
        sa.UniqueConstraint(
            "id", "gc_group_access_id", "agency_id", "group_id", name="uq_gc_announcement_scope"
        ),
    )
    op.create_index(
        "ix_gc_announcement_feed",
        "gc_announcements",
        ["gc_group_access_id", "status", "published_at"],
        unique=False,
    )
    op.create_index(
        "uq_gc_announcement_published",
        "gc_announcements",
        ["gc_group_access_id", "logical_announcement_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
        sqlite_where=sa.text("status = 'published'"),
    )
    op.create_table(
        "mobile_passenger_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=False),
        sa.Column("passenger_submission_id", sa.UUID(), nullable=False),
        sa.Column("normalized_phone_number", sa.String(length=16), nullable=False),
        sa.Column("phone_lookup_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("is_shared_number", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "requires_secondary_verification", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("secondary_factor_type", sa.String(length=32), nullable=True),
        sa.Column("secondary_factor_hash", sa.String(length=255), nullable=True),
        sa.Column("claim_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'claimed' AND claimed_at IS NOT NULL AND revoked_at IS NULL) OR (status IN ('pending', 'eligible') AND claimed_at IS NULL AND revoked_at IS NULL) OR (status = 'suspended' AND revoked_at IS NULL) OR (status = 'revoked' AND revoked_at IS NOT NULL)",
            name="ck_mobile_passenger_identity_state_shape",
        ),
        sa.CheckConstraint(
            "length(normalized_phone_number) BETWEEN 9 AND 16 AND normalized_phone_number LIKE '+%'",
            name="ck_mobile_passenger_identity_phone",
        ),
        sa.CheckConstraint(
            "secondary_factor_type IS NULL OR secondary_factor_type IN ('passenger_identifier', 'employee_code', 'date_of_birth', 'booking_code', 'invitation_token')",
            name="ck_mobile_passenger_identity_factor_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'eligible', 'claimed', 'suspended', 'revoked')",
            name="ck_mobile_passenger_identity_status",
        ),
        sa.CheckConstraint(
            "(secondary_factor_type IS NULL) = (secondary_factor_hash IS NULL)",
            name="ck_mobile_passenger_identity_factor_pair",
        ),
        sa.CheckConstraint(
            "NOT is_shared_number OR (requires_secondary_verification AND secondary_factor_type IS NOT NULL AND secondary_factor_hash IS NOT NULL)",
            name="ck_mobile_passenger_identity_shared",
        ),
        sa.CheckConstraint(
            "length(phone_lookup_hash) = 64", name="ck_mobile_passenger_identity_phone_hash"
        ),
        sa.CheckConstraint("claim_generation >= 0", name="ck_mobile_passenger_identity_generation"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_passenger_identity_access",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["passenger_submission_id"], ["passport_submissions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "gc_group_access_id",
            "passenger_submission_id",
            name="uq_mobile_passenger_identity_passenger",
        ),
        sa.UniqueConstraint("id", "agency_id", name="uq_mobile_passenger_identity_agency"),
        sa.UniqueConstraint(
            "id",
            "gc_group_access_id",
            "agency_id",
            "group_id",
            name="uq_mobile_passenger_identity_scope",
        ),
    )
    op.create_index(
        "ix_mobile_passenger_group_status",
        "mobile_passenger_identities",
        ["gc_group_access_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_passenger_phone_status",
        "mobile_passenger_identities",
        ["phone_lookup_hash", "status"],
        unique=False,
    )
    op.create_table(
        "mobile_document_metadata_cache",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=False),
        sa.Column("passenger_identity_id", sa.UUID(), nullable=False),
        sa.Column("passenger_submission_id", sa.UUID(), nullable=False),
        sa.Column("source_kind", sa.String(length=24), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("storage_key_hash", sa.String(length=64), nullable=False),
        sa.Column("safe_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_kind IN ('passport_front', 'passport_back', 'distributed')",
            name="ck_mobile_document_cache_source_kind",
        ),
        sa.CheckConstraint(
            "content_type IN ('application/pdf', 'image/jpeg', 'image/png', 'image/webp')",
            name="ck_mobile_document_cache_content_type",
        ),
        sa.CheckConstraint(
            "byte_size > 0 AND byte_size <= 104857600",
            name="ck_mobile_document_cache_size",
        ),
        sa.CheckConstraint(
            "length(storage_key_hash) = 64 AND length(checksum_sha256) = 64",
            name="ck_mobile_document_cache_hashes",
        ),
        sa.CheckConstraint("version >= 1", name="ck_mobile_document_cache_version"),
        sa.ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_document_cache_access",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["passenger_identity_id", "gc_group_access_id", "agency_id", "group_id"],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
            ],
            name="fk_mobile_document_cache_identity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["passenger_submission_id"],
            ["passport_submissions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "source_kind",
            "source_id",
            name="uq_mobile_document_cache_source",
        ),
    )
    op.create_index(
        "ix_mobile_document_cache_identity",
        "mobile_document_metadata_cache",
        ["passenger_identity_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_document_cache_access",
        "mobile_document_metadata_cache",
        ["gc_group_access_id", "updated_at"],
        unique=False,
    )
    op.create_table(
        "mobile_otp_challenges",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=True),
        sa.Column("passenger_identity_id", sa.UUID(), nullable=True),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("subject_type", sa.String(length=24), nullable=False),
        sa.Column("purpose", sa.String(length=16), server_default="login", nullable=False),
        sa.Column("phone_lookup_hash", sa.String(length=64), nullable=False),
        sa.Column("challenge_token_hash", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("resend_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_resends", sa.Integer(), nullable=False),
        sa.Column("resend_available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_ip_hash", sa.String(length=64), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'consumed' AND consumed_at IS NOT NULL) OR (status != 'consumed' AND consumed_at IS NULL)",
            name="ck_mobile_otp_consumed_shape",
        ),
        sa.CheckConstraint(
            "(status IN ('verified', 'consumed') AND verified_at IS NOT NULL) OR (status NOT IN ('verified', 'consumed') AND verified_at IS NULL)",
            name="ck_mobile_otp_verified_shape",
        ),
        sa.CheckConstraint(
            "purpose IN ('login', 'activation', 'step_up')", name="ck_mobile_otp_purpose"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'consumed', 'expired', 'locked', 'cancelled')",
            name="ck_mobile_otp_status",
        ),
        sa.CheckConstraint(
            "subject_type IN ('passenger', 'client_manager', 'coordinator')",
            name="ck_mobile_otp_subject_type",
        ),
        sa.CheckConstraint(
            "NOT (passenger_identity_id IS NOT NULL AND user_id IS NOT NULL)",
            name="ck_mobile_otp_single_subject",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20 AND attempt_count <= max_attempts",
            name="ck_mobile_otp_attempts",
        ),
        sa.CheckConstraint(
            "length(phone_lookup_hash) = 64 AND length(challenge_token_hash) = 64",
            name="ck_mobile_otp_lookup_hashes",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_mobile_otp_expiry"),
        sa.CheckConstraint(
            "resend_count >= 0 AND max_resends BETWEEN 0 AND 20 AND resend_count <= max_resends",
            name="ck_mobile_otp_resends",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["passenger_identity_id"], ["mobile_passenger_identities.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("challenge_token_hash"),
    )
    op.create_index(
        "ix_mobile_otp_expiry_status",
        "mobile_otp_challenges",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_otp_phone_created",
        "mobile_otp_challenges",
        ["phone_lookup_hash", "created_at"],
        unique=False,
    )
    op.create_table(
        "mobile_device_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("subject_role", sa.String(length=24), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("passenger_identity_id", sa.UUID(), nullable=True),
        sa.Column("passenger_subject_hash", sa.String(length=64), nullable=True),
        sa.Column("selected_gc_group_access_id", sa.UUID(), nullable=True),
        sa.Column("selected_group_id", sa.UUID(), nullable=True),
        sa.Column("device_identifier_hash", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("app_version", sa.String(length=32), nullable=False),
        sa.Column("device_label", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("session_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("refresh_family_id", sa.UUID(), nullable=False),
        sa.Column("created_ip_hash", sa.String(length=64), nullable=True),
        sa.Column("last_ip_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'active' AND revoked_at IS NULL) OR (status = 'revoked' AND revoked_at IS NOT NULL) OR status = 'expired'",
            name="ck_mobile_session_state_shape",
        ),
        sa.CheckConstraint(
            "(subject_role = 'passenger' AND user_id IS NULL AND passenger_subject_hash IS NOT NULL) OR (subject_role IN ('client_manager', 'coordinator') AND user_id IS NOT NULL AND passenger_identity_id IS NULL AND passenger_subject_hash IS NULL)",
            name="ck_mobile_session_subject_shape",
        ),
        sa.CheckConstraint(
            "passenger_identity_id IS NULL OR subject_role = 'passenger'",
            name="ck_mobile_session_passenger_role",
        ),
        sa.CheckConstraint("platform IN ('android', 'ios')", name="ck_mobile_session_platform"),
        sa.CheckConstraint(
            "status IN ('active', 'revoked', 'expired')", name="ck_mobile_session_status"
        ),
        sa.CheckConstraint(
            "subject_role IN ('passenger', 'client_manager', 'coordinator')",
            name="ck_mobile_session_subject_role",
        ),
        sa.CheckConstraint(
            "(selected_gc_group_access_id IS NULL) = (selected_group_id IS NULL)",
            name="ck_mobile_session_selected_group_pair",
        ),
        sa.CheckConstraint(
            "length(device_identifier_hash) = 64", name="ck_mobile_session_device_hash"
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_mobile_session_expiry"),
        sa.CheckConstraint("session_generation >= 0", name="ck_mobile_session_generation"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["passenger_identity_id", "agency_id"],
            ["mobile_passenger_identities.id", "mobile_passenger_identities.agency_id"],
            name="fk_mobile_session_passenger",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["selected_gc_group_access_id", "agency_id", "selected_group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_session_selected_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "agency_id", "refresh_family_id", name="uq_mobile_session_refresh_family"
        ),
        sa.UniqueConstraint("id", "agency_id", name="uq_mobile_session_agency"),
    )
    op.create_index(
        "ix_mobile_session_agency_seen",
        "mobile_device_sessions",
        ["agency_id", "last_seen_at"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_session_expiry", "mobile_device_sessions", ["status", "expires_at"], unique=False
    )
    op.create_index(
        "uq_mobile_session_passenger_device_active",
        "mobile_device_sessions",
        ["passenger_subject_hash", "device_identifier_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND passenger_subject_hash IS NOT NULL"),
        sqlite_where=sa.text("status = 'active' AND passenger_subject_hash IS NOT NULL"),
    )
    op.create_index(
        "uq_mobile_session_user_device_active",
        "mobile_device_sessions",
        ["user_id", "device_identifier_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND user_id IS NOT NULL"),
        sqlite_where=sa.text("status = 'active' AND user_id IS NOT NULL"),
    )
    op.create_table(
        "mobile_refresh_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("parent_token_id", sa.UUID(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_generation", sa.Integer(), nullable=False),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=80), nullable=True),
        sa.Column("reuse_detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND revoke_reason IS NULL) OR revoked_at IS NOT NULL",
            name="ck_mobile_refresh_revocation_shape",
        ),
        sa.CheckConstraint("length(token_hash) = 64", name="ck_mobile_refresh_token_hash"),
        sa.CheckConstraint("expires_at > issued_at", name="ck_mobile_refresh_expiry"),
        sa.CheckConstraint(
            "reuse_detected_at IS NULL OR revoked_at IS NOT NULL",
            name="ck_mobile_refresh_reuse_shape",
        ),
        sa.CheckConstraint("token_generation >= 1", name="ck_mobile_refresh_generation"),
        sa.ForeignKeyConstraint(
            ["parent_token_id", "session_id", "agency_id", "family_id"],
            [
                "mobile_refresh_tokens.id",
                "mobile_refresh_tokens.session_id",
                "mobile_refresh_tokens.agency_id",
                "mobile_refresh_tokens.family_id",
            ],
            name="fk_mobile_refresh_parent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "agency_id", "family_id"],
            [
                "mobile_device_sessions.id",
                "mobile_device_sessions.agency_id",
                "mobile_device_sessions.refresh_family_id",
            ],
            name="fk_mobile_refresh_session_family",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "session_id", "agency_id", "family_id", name="uq_mobile_refresh_token_scope"
        ),
        sa.UniqueConstraint(
            "session_id", "token_generation", name="uq_mobile_refresh_session_generation"
        ),
        sa.UniqueConstraint("token_hash", name="uq_mobile_refresh_token_hash"),
    )
    op.create_index(
        "ix_mobile_refresh_active",
        "mobile_refresh_tokens",
        ["session_id", "expires_at"],
        unique=False,
        postgresql_where=sa.text("consumed_at IS NULL AND revoked_at IS NULL"),
        sqlite_where=sa.text("consumed_at IS NULL AND revoked_at IS NULL"),
    )
    op.create_index(
        "ix_mobile_refresh_family",
        "mobile_refresh_tokens",
        ["family_id", "token_generation"],
        unique=False,
    )
    op.create_table(
        "mobile_push_registrations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("app_bundle_id", sa.String(length=255), nullable=False),
        sa.Column("token_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("token_lookup_hash", sa.String(length=64), nullable=False),
        sa.Column("token_key_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("notifications_authorized", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "last_registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_code", sa.String(length=80), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) OR (status != 'revoked' AND revoked_at IS NULL)",
            name="ck_mobile_push_revoked_shape",
        ),
        sa.CheckConstraint(
            "environment IN ('development', 'production')", name="ck_mobile_push_environment"
        ),
        sa.CheckConstraint("platform IN ('android', 'ios')", name="ck_mobile_push_platform"),
        sa.CheckConstraint("provider IN ('expo', 'fcm', 'apns')", name="ck_mobile_push_provider"),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'revoked')", name="ck_mobile_push_status"
        ),
        sa.CheckConstraint(
            "length(token_ciphertext) > 0 AND length(token_lookup_hash) = 64",
            name="ck_mobile_push_token_material",
        ),
        sa.CheckConstraint("token_key_version >= 1", name="ck_mobile_push_key_version"),
        sa.ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["mobile_device_sessions.id", "mobile_device_sessions.agency_id"],
            name="fk_mobile_push_session",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "token_lookup_hash", name="uq_mobile_push_provider_token"),
    )
    op.create_index(
        "ix_mobile_push_failure",
        "mobile_push_registrations",
        ["status", "last_failure_at"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_push_session_status",
        "mobile_push_registrations",
        ["session_id", "status"],
        unique=False,
    )
    op.create_table(
        "mobile_notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=True),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=True),
        sa.Column("recipient_type", sa.String(length=24), nullable=False),
        sa.Column("recipient_user_id", sa.UUID(), nullable=True),
        sa.Column("recipient_passenger_identity_id", sa.UUID(), nullable=True),
        sa.Column("notification_type", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=16), server_default="normal", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("lock_screen_title", sa.String(length=120), nullable=True),
        sa.Column("lock_screen_body", sa.String(length=240), nullable=True),
        sa.Column(
            "contains_sensitive_content", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("deep_link_path", sa.String(length=512), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column(
            "public_payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(recipient_type = 'passenger' AND recipient_passenger_identity_id IS NOT NULL AND recipient_user_id IS NULL) OR (recipient_type IN ('client_manager', 'coordinator') AND recipient_user_id IS NOT NULL AND recipient_passenger_identity_id IS NULL)",
            name="ck_mobile_notification_recipient_shape",
        ),
        sa.CheckConstraint(
            "category IN ('announcement', 'itinerary', 'room', 'flight', 'document', 'coordinator', 'emergency', 'security', 'sync')",
            name="ck_mobile_notification_category",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'emergency')",
            name="ck_mobile_notification_priority",
        ),
        sa.CheckConstraint(
            "recipient_type IN ('passenger', 'client_manager', 'coordinator')",
            name="ck_mobile_notification_recipient_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'failed', 'cancelled')",
            name="ck_mobile_notification_status",
        ),
        sa.CheckConstraint(
            "NOT contains_sensitive_content OR lock_screen_body IS NULL",
            name="ck_mobile_notification_lock_screen_privacy",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > available_at", name="ck_mobile_notification_expiry"
        ),
        sa.CheckConstraint(
            "(gc_group_access_id IS NULL) = (group_id IS NULL)",
            name="ck_mobile_notification_group_pair",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_notification_access",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_passenger_identity_id"],
            ["mobile_passenger_identities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mobile_notification_delivery",
        "mobile_notifications",
        ["status", "available_at"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_notification_passenger_feed",
        "mobile_notifications",
        ["recipient_passenger_identity_id", "read_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_notification_user_feed",
        "mobile_notifications",
        ["recipient_user_id", "read_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_mobile_notification_passenger_dedupe",
        "mobile_notifications",
        ["recipient_passenger_identity_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("recipient_passenger_identity_id IS NOT NULL"),
        sqlite_where=sa.text("recipient_passenger_identity_id IS NOT NULL"),
    )
    op.create_index(
        "uq_mobile_notification_user_dedupe",
        "mobile_notifications",
        ["recipient_user_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("recipient_user_id IS NOT NULL"),
        sqlite_where=sa.text("recipient_user_id IS NOT NULL"),
    )
    op.create_table(
        "mobile_sync_changes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=False),
        sa.Column("passenger_identity_id", sa.UUID(), nullable=True),
        sa.Column("audience", sa.String(length=24), server_default="all", nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("access_generation", sa.Integer(), nullable=False),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("payload_checksum", sa.String(length=64), nullable=True),
        sa.Column("changed_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "audience IN ('all', 'passenger', 'client_manager', 'coordinator')",
            name="ck_mobile_sync_change_audience",
        ),
        sa.CheckConstraint(
            "operation IN ('upsert', 'delete', 'revoke', 'publish')",
            name="ck_mobile_sync_change_operation",
        ),
        sa.CheckConstraint(
            "passenger_identity_id IS NULL OR audience = 'passenger'",
            name="ck_mobile_sync_change_passenger_audience",
        ),
        sa.CheckConstraint("access_generation >= 0", name="ck_mobile_sync_change_generation"),
        sa.CheckConstraint(
            "payload_checksum IS NULL OR length(payload_checksum) = 64",
            name="ck_mobile_sync_change_checksum",
        ),
        sa.CheckConstraint("version >= 1", name="ck_mobile_sync_change_version"),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_sync_change_access",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["passenger_identity_id", "gc_group_access_id", "agency_id", "group_id"],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
            ],
            name="fk_mobile_sync_change_passenger",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("sequence"),
        sa.UniqueConstraint("id", name="uq_mobile_sync_change_id"),
    )
    op.create_index(
        "ix_mobile_sync_change_agency_cursor",
        "mobile_sync_changes",
        ["agency_id", "sequence"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_sync_change_expiry", "mobile_sync_changes", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_mobile_sync_change_group_cursor",
        "mobile_sync_changes",
        ["gc_group_access_id", "sequence"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_sync_change_passenger_cursor",
        "mobile_sync_changes",
        ["passenger_identity_id", "sequence"],
        unique=False,
    )
    op.create_table(
        "passenger_family_delegations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=False),
        sa.Column("lead_identity_id", sa.UUID(), nullable=False),
        sa.Column("dependent_identity_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("can_view_trip_data", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("can_view_documents", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("can_view_qr", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.UUID(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) OR (status != 'revoked' AND revoked_at IS NULL)",
            name="ck_passenger_family_revoked_shape",
        ),
        sa.CheckConstraint(
            "NOT is_enabled OR status = 'active'", name="ck_passenger_family_enabled_status"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'revoked', 'expired')",
            name="ck_passenger_family_status",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR effective_at IS NULL OR expires_at > effective_at",
            name="ck_passenger_family_window",
        ),
        sa.CheckConstraint(
            "lead_identity_id != dependent_identity_id", name="ck_passenger_family_not_self"
        ),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["dependent_identity_id", "gc_group_access_id", "agency_id", "group_id"],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
            ],
            name="fk_passenger_family_dependent",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lead_identity_id", "gc_group_access_id", "agency_id", "group_id"],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
            ],
            name="fk_passenger_family_lead",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "lead_identity_id", "dependent_identity_id", name="uq_passenger_family_delegation_pair"
        ),
    )
    op.create_index(
        "ix_passenger_family_dependent_status",
        "passenger_family_delegations",
        ["dependent_identity_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_passenger_family_lead_status",
        "passenger_family_delegations",
        ["lead_identity_id", "status"],
        unique=False,
    )
    op.create_table(
        "mobile_idempotency_receipts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=True),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="processing", nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=True),
        sa.Column("response_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "response_payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(status = 'processing' AND completed_at IS NULL) OR (status != 'processing' AND completed_at IS NOT NULL)",
            name="ck_mobile_idempotency_completion",
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'failed', 'conflict')",
            name="ck_mobile_idempotency_status",
        ),
        sa.CheckConstraint(
            "(gc_group_access_id IS NULL) = (group_id IS NULL)",
            name="ck_mobile_idempotency_group_pair",
        ),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_mobile_idempotency_request_hash"),
        sa.CheckConstraint("expires_at > created_at", name="ck_mobile_idempotency_expiry"),
        sa.CheckConstraint(
            "response_hash IS NULL OR length(response_hash) = 64",
            name="ck_mobile_idempotency_response_hash",
        ),
        sa.ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_idempotency_access",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "agency_id"],
            ["mobile_device_sessions.id", "mobile_device_sessions.agency_id"],
            name="fk_mobile_idempotency_session",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "idempotency_key", name="uq_mobile_idempotency_session_key"
        ),
    )
    op.create_index(
        "ix_mobile_idempotency_expiry", "mobile_idempotency_receipts", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_mobile_idempotency_status",
        "mobile_idempotency_receipts",
        ["status", "created_at"],
        unique=False,
    )
    op.create_table(
        "mobile_incidents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("agency_id", sa.UUID(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("gc_group_access_id", sa.UUID(), nullable=False),
        sa.Column("created_by_session_id", sa.UUID(), nullable=False),
        sa.Column("reported_by_user_id", sa.UUID(), nullable=True),
        sa.Column("affected_passenger_identity_id", sa.UUID(), nullable=True),
        sa.Column("client_event_id", sa.String(length=64), nullable=False),
        sa.Column("incident_type", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location_text", sa.String(length=500), nullable=True),
        sa.Column("is_confidential", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_offline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_user_id", sa.UUID(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status IN ('resolved', 'closed') AND resolved_at IS NOT NULL) OR (status IN ('open', 'acknowledged') AND resolved_at IS NULL)",
            name="ck_mobile_incident_resolution",
        ),
        sa.CheckConstraint(
            "incident_type IN ('missing_passenger', 'medical', 'safety', 'transport', 'hotel', 'document', 'meal', 'other')",
            name="ck_mobile_incident_type",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')", name="ck_mobile_incident_severity"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved', 'closed')",
            name="ck_mobile_incident_status",
        ),
        sa.ForeignKeyConstraint(
            ["affected_passenger_identity_id"],
            ["mobile_passenger_identities.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_session_id", "agency_id"],
            ["mobile_device_sessions.id", "mobile_device_sessions.agency_id"],
            name="fk_mobile_incident_session",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_mobile_incident_access",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["reported_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "created_by_session_id", "client_event_id", name="uq_mobile_incident_session_event"
        ),
    )
    op.create_index(
        "ix_mobile_incident_group_status",
        "mobile_incidents",
        ["gc_group_access_id", "status", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_mobile_incident_severity",
        "mobile_incidents",
        ["severity", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    for table_name in reversed(_TABLES_IN_DEPENDENCY_ORDER):
        op.drop_table(table_name)

    # PostgreSQL cannot remove an enum value in place. Leaving the unused
    # value is safer than rebuilding the shared users.role type during rollback.
