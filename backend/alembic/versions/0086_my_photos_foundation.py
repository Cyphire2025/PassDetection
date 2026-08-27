"""Add provider-neutral, trip-scoped My Photos foundation.

Revision ID: 0086_my_photos_foundation
Revises: 0085_platform_retention_controls
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0086_my_photos_foundation"
down_revision = "0085_platform_retention_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _create_galleries()
    _create_manifests()
    _create_assets()
    _create_variants()
    _create_face_occurrences()
    _create_enrollments()
    _create_liveness_sessions()
    _create_search_runs()
    _create_matches()
    _create_jobs()
    _create_delivery_authorizations()


def _create_galleries() -> None:
    op.create_table(
        "my_photo_galleries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gc_group_access_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="not_uploaded", nullable=False),
        sa.Column("media_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("face_index_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("published_revision", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("total_asset_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("indexed_asset_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_asset_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "all_group_photos_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("provider_collection_reference", sa.String(length=512), nullable=True),
        sa.Column("provider_name", sa.String(length=32), nullable=True),
        sa.Column("index_model_version", sa.String(length=64), nullable=True),
        sa.Column(
            "match_config_version",
            sa.String(length=64),
            server_default="unconfigured",
            nullable=False,
        ),
        sa.Column(
            "retention_policy_version", sa.String(length=64), server_default="v1", nullable=False
        ),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("availability_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("availability_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('not_uploaded', 'awaiting_upload', 'processing', 'indexing', "
            "'ready', 'failed', 'removed')",
            name="ck_my_photo_gallery_status",
        ),
        sa.CheckConstraint(
            "media_version >= 0 AND face_index_version >= 0 AND published_revision >= 0",
            name="ck_my_photo_gallery_versions",
        ),
        sa.CheckConstraint(
            "total_asset_count >= 0 AND indexed_asset_count >= 0 AND failed_asset_count >= 0 "
            "AND indexed_asset_count + failed_asset_count <= total_asset_count",
            name="ck_my_photo_gallery_counts",
        ),
        sa.CheckConstraint(
            "availability_ends_at IS NULL OR availability_starts_at IS NULL "
            "OR availability_ends_at > availability_starts_at",
            name="ck_my_photo_gallery_window",
        ),
        sa.CheckConstraint(
            "retention_days IS NULL OR retention_days BETWEEN 1 AND 3650",
            name="ck_my_photo_gallery_retention",
        ),
        sa.CheckConstraint(
            "(status = 'ready' AND published_revision >= 1 AND published_at IS NOT NULL "
            "AND provider_collection_reference IS NOT NULL) OR status != 'ready'",
            name="ck_my_photo_gallery_ready_shape",
        ),
        sa.ForeignKeyConstraint(["agency_id"], ["agencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["client_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["gc_group_access_id", "agency_id", "group_id"],
            ["gc_group_access.id", "gc_group_access.agency_id", "gc_group_access.group_id"],
            name="fk_my_photo_gallery_access",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", name="uq_my_photo_gallery_group"),
        sa.UniqueConstraint(
            "gc_group_access_id", "agency_id", "group_id", name="uq_my_photo_gallery_access"
        ),
        sa.UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_gallery_scope"),
    )
    op.create_index(
        "ix_my_photo_gallery_availability",
        "my_photo_galleries",
        ["feature_enabled", "status", "group_id"],
    )
    op.create_index(
        "ix_my_photo_gallery_revision",
        "my_photo_galleries",
        ["group_id", "published_revision"],
    )


def _create_manifests() -> None:
    op.create_table(
        "my_photo_gallery_manifests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gallery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manifest_identity", sa.String(length=128), nullable=False),
        sa.Column("target_revision", sa.BigInteger(), nullable=False),
        sa.Column("header_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("total_asset_count", sa.Integer(), nullable=False),
        sa.Column("batch_count", sa.Integer(), nullable=False),
        sa.Column("received_asset_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="receiving", nullable=False),
        sa.Column(
            "all_group_photos_enabled",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("retention_policy_version", sa.String(length=64), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("availability_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("availability_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_collection_reference", sa.String(length=512), nullable=False),
        sa.Column("provider_model_version", sa.String(length=64), nullable=False),
        sa.Column("match_config_version", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('receiving', 'finalized', 'indexing', 'failed', 'cancelled')",
            name="ck_my_photo_manifest_status",
        ),
        sa.CheckConstraint(
            "target_revision >= 1 AND total_asset_count BETWEEN 1 AND 5000 "
            "AND batch_count BETWEEN 1 AND 50 AND received_asset_count >= 0 "
            "AND received_asset_count <= total_asset_count",
            name="ck_my_photo_manifest_counts",
        ),
        sa.CheckConstraint(
            "length(header_fingerprint) = 64 AND header_fingerprint = lower(header_fingerprint) "
            "AND (content_fingerprint IS NULL OR "
            "(length(content_fingerprint) = 64 "
            "AND content_fingerprint = lower(content_fingerprint)))",
            name="ck_my_photo_manifest_fingerprints",
        ),
        sa.CheckConstraint(
            "retention_days BETWEEN 1 AND 3650 AND availability_ends_at > availability_starts_at",
            name="ck_my_photo_manifest_policy",
        ),
        sa.ForeignKeyConstraint(
            ["gallery_id", "agency_id", "group_id"],
            [
                "my_photo_galleries.id",
                "my_photo_galleries.agency_id",
                "my_photo_galleries.group_id",
            ],
            name="fk_my_photo_manifest_gallery",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_manifest_scope"),
        sa.UniqueConstraint(
            "gallery_id", "manifest_identity", name="uq_my_photo_manifest_identity"
        ),
    )
    op.create_index(
        "ix_my_photo_manifest_status",
        "my_photo_gallery_manifests",
        ["status", "created_at"],
    )
    op.create_index(
        "uq_my_photo_manifest_active_revision",
        "my_photo_gallery_manifests",
        ["gallery_id", "target_revision"],
        unique=True,
        postgresql_where=sa.text("status <> 'cancelled'"),
    )
    op.create_table(
        "my_photo_gallery_manifest_batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manifest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("batch_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("asset_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "batch_index BETWEEN 0 AND 49 AND asset_count BETWEEN 1 AND 100",
            name="ck_my_photo_manifest_batch_bounds",
        ),
        sa.CheckConstraint(
            "length(batch_fingerprint) = 64 AND batch_fingerprint = lower(batch_fingerprint)",
            name="ck_my_photo_manifest_batch_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["manifest_id", "agency_id", "group_id"],
            [
                "my_photo_gallery_manifests.id",
                "my_photo_gallery_manifests.agency_id",
                "my_photo_gallery_manifests.group_id",
            ],
            name="fk_my_photo_manifest_batch_manifest",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("manifest_id", "batch_index", name="uq_my_photo_manifest_batch"),
    )


def _create_assets() -> None:
    op.create_table(
        "my_photo_media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gallery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("immutable_asset_key", sa.String(length=128), nullable=False),
        sa.Column("media_type", sa.String(length=16), server_default="photo", nullable=False),
        sa.Column("archive_reference", sa.String(length=4096), nullable=True),
        sa.Column("storage_reference", sa.String(length=4096), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("aspect_ratio", sa.Float(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("orientation", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "processing_state", sa.String(length=24), server_default="registered", nullable=False
        ),
        sa.Column(
            "availability_state", sa.String(length=32), server_default="registered", nullable=False
        ),
        sa.Column("published_revision", sa.BigInteger(), nullable=False),
        sa.Column("sort_rank", sa.BigInteger(), nullable=False),
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
        sa.CheckConstraint("media_type = 'photo'", name="ck_my_photo_asset_media_type"),
        sa.CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png', 'image/webp', 'image/heic')",
            name="ck_my_photo_asset_mime",
        ),
        sa.CheckConstraint(
            "width BETWEEN 1 AND 100000 AND height BETWEEN 1 AND 100000 "
            "AND aspect_ratio > 0 AND aspect_ratio <= 100",
            name="ck_my_photo_asset_dimensions",
        ),
        sa.CheckConstraint("byte_size BETWEEN 1 AND 209715200", name="ck_my_photo_asset_size"),
        sa.CheckConstraint(
            "length(checksum_sha256) = 64 AND checksum_sha256 = lower(checksum_sha256)",
            name="ck_my_photo_asset_checksum",
        ),
        sa.CheckConstraint("orientation BETWEEN 1 AND 8", name="ck_my_photo_asset_orientation"),
        sa.CheckConstraint(
            "published_revision >= 1 AND sort_rank >= 0",
            name="ck_my_photo_asset_revision_rank",
        ),
        sa.CheckConstraint(
            "processing_state IN ('registered', 'awaiting_upload', 'processing', 'indexed', "
            "'failed', 'removed')",
            name="ck_my_photo_asset_processing",
        ),
        sa.CheckConstraint(
            "availability_state IN ('registered', 'awaiting_upload', 'processing', 'indexed', "
            "'preview_available', 'original_available_online', 'archived_offline', "
            "'rehydration_requested', 'preparing_delivery', 'delivery_available', 'expired', "
            "'failed', 'removed')",
            name="ck_my_photo_asset_availability",
        ),
        sa.CheckConstraint(
            "length(trim(original_filename)) BETWEEN 1 AND 255 "
            "AND original_filename NOT LIKE '%/%' AND original_filename NOT LIKE '%\\%'",
            name="ck_my_photo_asset_filename",
        ),
        sa.CheckConstraint(
            "(archive_reference IS NULL OR archive_reference NOT LIKE '%://%') AND "
            "(storage_reference IS NULL OR storage_reference NOT LIKE '%://%')",
            name="ck_my_photo_asset_refs",
        ),
        sa.ForeignKeyConstraint(
            ["gallery_id", "agency_id", "group_id"],
            [
                "my_photo_galleries.id",
                "my_photo_galleries.agency_id",
                "my_photo_galleries.group_id",
            ],
            name="fk_my_photo_asset_gallery",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_asset_scope"),
        sa.UniqueConstraint(
            "gallery_id", "immutable_asset_key", name="uq_my_photo_asset_gallery_key"
        ),
    )
    op.create_index(
        "ix_my_photo_asset_gallery_page",
        "my_photo_media_assets",
        ["gallery_id", "published_revision", "sort_rank", "id"],
    )
    op.create_index(
        "ix_my_photo_asset_availability",
        "my_photo_media_assets",
        ["gallery_id", "availability_state", "id"],
    )
    op.create_index(
        "ix_my_photo_asset_checksum",
        "my_photo_media_assets",
        ["gallery_id", "checksum_sha256"],
    )


def _create_variants() -> None:
    op.create_table(
        "my_photo_asset_variants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variant_kind", sa.String(length=16), nullable=False),
        sa.Column("storage_reference", sa.String(length=4096), nullable=True),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("availability_state", sa.String(length=32), nullable=False),
        sa.Column("delivery_version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
            "variant_kind IN ('thumbnail', 'preview', 'analysis', 'original', 'optimized')",
            name="ck_my_photo_variant_kind",
        ),
        sa.CheckConstraint(
            "availability_state IN ('registered', 'awaiting_upload', 'processing', 'indexed', "
            "'preview_available', 'original_available_online', 'archived_offline', "
            "'rehydration_requested', 'preparing_delivery', 'delivery_available', 'expired', "
            "'failed', 'removed')",
            name="ck_my_photo_variant_availability",
        ),
        sa.CheckConstraint(
            "width BETWEEN 1 AND 100000 AND height BETWEEN 1 AND 100000 "
            "AND byte_size BETWEEN 1 AND 209715200",
            name="ck_my_photo_variant_dimensions",
        ),
        sa.CheckConstraint(
            "length(checksum_sha256) = 64 AND checksum_sha256 = lower(checksum_sha256)",
            name="ck_my_photo_variant_checksum",
        ),
        sa.CheckConstraint(
            "storage_reference IS NULL OR storage_reference NOT LIKE '%://%'",
            name="ck_my_photo_variant_ref",
        ),
        sa.CheckConstraint("delivery_version >= 1", name="ck_my_photo_variant_version"),
        sa.ForeignKeyConstraint(
            ["media_asset_id", "agency_id", "group_id"],
            [
                "my_photo_media_assets.id",
                "my_photo_media_assets.agency_id",
                "my_photo_media_assets.group_id",
            ],
            name="fk_my_photo_variant_asset",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_variant_scope"),
        sa.UniqueConstraint(
            "media_asset_id", "variant_kind", "delivery_version", name="uq_my_photo_variant_version"
        ),
    )
    op.create_index(
        "ix_my_photo_variant_delivery",
        "my_photo_asset_variants",
        ["media_asset_id", "variant_kind", "availability_state"],
    )


def _create_face_occurrences() -> None:
    op.create_table(
        "my_photo_face_occurrences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_name", sa.String(length=32), nullable=False),
        sa.Column("provider_face_reference", sa.String(length=512), nullable=False),
        sa.Column("idempotency_identity", sa.String(length=128), nullable=False),
        sa.Column("bounding_left", sa.Float(), nullable=False),
        sa.Column("bounding_top", sa.Float(), nullable=False),
        sa.Column("bounding_width", sa.Float(), nullable=False),
        sa.Column("bounding_height", sa.Float(), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("quality_class", sa.String(length=32), nullable=True),
        sa.Column("provider_model_version", sa.String(length=64), nullable=False),
        sa.Column("index_version", sa.BigInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "bounding_left BETWEEN 0 AND 1 AND bounding_top BETWEEN 0 AND 1 "
            "AND bounding_width > 0 AND bounding_width <= 1 "
            "AND bounding_height > 0 AND bounding_height <= 1 "
            "AND bounding_left + bounding_width <= 1.000001 "
            "AND bounding_top + bounding_height <= 1.000001",
            name="ck_my_photo_face_bounds",
        ),
        sa.CheckConstraint(
            "quality_score IS NULL OR quality_score BETWEEN 0 AND 100",
            name="ck_my_photo_face_quality",
        ),
        sa.CheckConstraint("index_version >= 1", name="ck_my_photo_face_index_version"),
        sa.CheckConstraint(
            "(active = true AND deleted_at IS NULL) OR (active = false)",
            name="ck_my_photo_face_active",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id", "agency_id", "group_id"],
            [
                "my_photo_media_assets.id",
                "my_photo_media_assets.agency_id",
                "my_photo_media_assets.group_id",
            ],
            name="fk_my_photo_face_asset",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_face_scope"),
        sa.UniqueConstraint(
            "id", "media_asset_id", "agency_id", "group_id", name="uq_my_photo_face_asset_scope"
        ),
        sa.UniqueConstraint(
            "agency_id",
            "group_id",
            "provider_name",
            "index_version",
            "provider_face_reference",
            name="uq_my_photo_face_provider",
        ),
        sa.UniqueConstraint(
            "media_asset_id", "idempotency_identity", name="uq_my_photo_face_idempotency"
        ),
    )
    op.create_index(
        "ix_my_photo_face_asset_active",
        "my_photo_face_occurrences",
        ["media_asset_id", "active"],
    )


def _create_enrollments() -> None:
    op.create_table(
        "my_photo_enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gc_group_access_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consent_version", sa.String(length=64), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="ready", nullable=False),
        sa.Column("provider_name", sa.String(length=32), nullable=True),
        sa.Column("provider_reference_handle", sa.String(length=4096), nullable=True),
        sa.Column("reference_version", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deletion_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("deletion_scope", sa.String(length=40), nullable=True),
        sa.Column(
            "provider_deletion_status",
            sa.String(length=16),
            server_default="not_required",
            nullable=False,
        ),
        sa.Column("provider_deletion_error_code", sa.String(length=64), nullable=True),
        sa.Column("provider_deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_deletion_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_provider_reference_handle", sa.String(length=4096), nullable=True),
        sa.Column(
            "superseded_reference_deletion_status",
            sa.String(length=16),
            server_default="not_required",
            nullable=False,
        ),
        sa.Column("superseded_reference_deletion_error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "superseded_reference_deletion_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "superseded_reference_deletion_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "provider_deletion_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "provider_deletion_next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "provider_deletion_last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "superseded_deletion_attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "superseded_deletion_next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "superseded_deletion_last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
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
            "status IN ('ready', 'session_pending', 'processing', 'enrolled', 'rejected', "
            "'cooldown', 'revoked', 'deleted')",
            name="ck_my_photo_enrollment_status",
        ),
        sa.CheckConstraint(
            "length(trim(consent_version)) BETWEEN 1 AND 64",
            name="ck_my_photo_enrollment_consent",
        ),
        sa.CheckConstraint(
            "reference_version >= 0 AND attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20",
            name="ck_my_photo_enrollment_attempts",
        ),
        sa.CheckConstraint(
            "(status = 'cooldown' AND cooldown_until IS NOT NULL) OR status != 'cooldown'",
            name="ck_my_photo_enrollment_cooldown",
        ),
        sa.CheckConstraint(
            "(status = 'revoked' AND revoked_at IS NOT NULL) OR "
            "(status = 'deleted' AND deleted_at IS NOT NULL) OR "
            "status NOT IN ('revoked', 'deleted')",
            name="ck_my_photo_enrollment_terminal",
        ),
        sa.CheckConstraint(
            "(status = 'enrolled' AND provider_reference_handle IS NOT NULL "
            "AND reference_version >= 1 AND enrolled_at IS NOT NULL) OR status != 'enrolled'",
            name="ck_my_photo_enrollment_enrolled",
        ),
        sa.CheckConstraint(
            "provider_deletion_status IN ('not_required', 'pending', 'complete', 'failed')",
            name="ck_my_photo_enrollment_provider_deletion_status",
        ),
        sa.CheckConstraint(
            "(deletion_idempotency_key IS NULL AND deletion_scope IS NULL) OR "
            "(deletion_idempotency_key IS NOT NULL AND deletion_scope IN "
            "('enrollment_only', 'enrollment_and_search_data'))",
            name="ck_my_photo_enrollment_deletion_request",
        ),
        sa.CheckConstraint(
            "(status = 'deleted' AND deletion_idempotency_key IS NOT NULL) OR status != 'deleted'",
            name="ck_my_photo_enrollment_deleted_request",
        ),
        sa.CheckConstraint(
            "(provider_deletion_status = 'not_required' "
            "AND provider_deletion_requested_at IS NULL "
            "AND provider_deletion_completed_at IS NULL "
            "AND provider_deletion_error_code IS NULL) OR "
            "(provider_deletion_status = 'pending' "
            "AND provider_deletion_requested_at IS NOT NULL "
            "AND provider_deletion_completed_at IS NULL) OR "
            "(provider_deletion_status = 'complete' "
            "AND provider_deletion_requested_at IS NOT NULL "
            "AND provider_deletion_completed_at IS NOT NULL "
            "AND provider_deletion_error_code IS NULL "
            "AND provider_reference_handle IS NULL) OR "
            "(provider_deletion_status = 'failed' "
            "AND provider_deletion_requested_at IS NOT NULL "
            "AND provider_deletion_completed_at IS NULL "
            "AND provider_deletion_error_code IS NOT NULL)",
            name="ck_my_photo_enrollment_provider_deletion_shape",
        ),
        sa.CheckConstraint(
            "superseded_reference_deletion_status IN "
            "('not_required', 'pending', 'complete', 'failed')",
            name="ck_my_photo_enrollment_superseded_deletion_status",
        ),
        sa.CheckConstraint(
            "provider_deletion_attempt_count BETWEEN 0 AND 20",
            name="ck_my_photo_enrollment_deletion_attempts",
        ),
        sa.CheckConstraint(
            "superseded_deletion_attempt_count BETWEEN 0 AND 20",
            name="ck_my_photo_enrollment_superseded_deletion_attempts",
        ),
        sa.CheckConstraint(
            "(superseded_reference_deletion_status = 'not_required' "
            "AND superseded_provider_reference_handle IS NULL "
            "AND superseded_reference_deletion_requested_at IS NULL "
            "AND superseded_reference_deletion_completed_at IS NULL "
            "AND superseded_reference_deletion_error_code IS NULL) OR "
            "(superseded_reference_deletion_status = 'pending' "
            "AND superseded_provider_reference_handle IS NOT NULL "
            "AND superseded_reference_deletion_requested_at IS NOT NULL "
            "AND superseded_reference_deletion_completed_at IS NULL) OR "
            "(superseded_reference_deletion_status = 'complete' "
            "AND superseded_provider_reference_handle IS NULL "
            "AND superseded_reference_deletion_requested_at IS NOT NULL "
            "AND superseded_reference_deletion_completed_at IS NOT NULL "
            "AND superseded_reference_deletion_error_code IS NULL) OR "
            "(superseded_reference_deletion_status = 'failed' "
            "AND superseded_provider_reference_handle IS NOT NULL "
            "AND superseded_reference_deletion_requested_at IS NOT NULL "
            "AND superseded_reference_deletion_completed_at IS NULL "
            "AND superseded_reference_deletion_error_code IS NOT NULL)",
            name="ck_my_photo_enrollment_superseded_deletion_shape",
        ),
        sa.ForeignKeyConstraint(
            [
                "passenger_identity_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
                "passenger_submission_id",
            ],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
                "mobile_passenger_identities.passenger_submission_id",
            ],
            name="fk_my_photo_enrollment_passenger",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_enrollment_scope"),
        sa.UniqueConstraint(
            "id",
            "passenger_identity_id",
            "agency_id",
            "group_id",
            name="uq_my_photo_enrollment_passenger_scope",
        ),
        sa.UniqueConstraint(
            "passenger_identity_id", "group_id", name="uq_my_photo_enrollment_passenger"
        ),
    )
    op.create_index(
        "ix_my_photo_enrollment_group_status",
        "my_photo_enrollments",
        ["group_id", "status"],
    )
    op.create_index(
        "ix_my_photo_enrollment_deletion_retry",
        "my_photo_enrollments",
        ["provider_deletion_next_attempt_at", "provider_deletion_attempt_count"],
    )
    op.create_index(
        "ix_my_photo_enrollment_superseded_deletion_retry",
        "my_photo_enrollments",
        ["superseded_deletion_next_attempt_at", "superseded_deletion_attempt_count"],
    )


def _create_liveness_sessions() -> None:
    op.create_table(
        "my_photo_liveness_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("challenge_mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="created", nullable=False),
        sa.Column("provider_name", sa.String(length=32), nullable=False),
        sa.Column("provider_session_reference", sa.String(length=512), nullable=True),
        sa.Column("native_launch_handle", sa.String(length=512), nullable=True),
        sa.Column("stable_error_code", sa.String(length=64), nullable=True),
        sa.Column("completion_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("completion_outcome", sa.String(length=16), nullable=True),
        sa.Column("result_retryable", sa.Boolean(), nullable=True),
        sa.Column("provider_claim_token", sa.String(length=64), nullable=True),
        sa.Column("provider_claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
            "challenge_mode IN ('movement_and_light', 'movement_only')",
            name="ck_my_photo_liveness_mode",
        ),
        sa.CheckConstraint(
            "status IN ('creating', 'created', 'running', 'completed', 'cancelled', 'expired', "
            "'rejected', 'failed')",
            name="ck_my_photo_liveness_status",
        ),
        sa.CheckConstraint("expires_at > created_at", name="ck_my_photo_liveness_expiry"),
        sa.CheckConstraint(
            "(provider_session_reference IS NULL AND status IN ('creating', 'failed')) OR "
            "(provider_session_reference IS NOT NULL AND status != 'creating')",
            name="ck_my_photo_liveness_provider_reference",
        ),
        sa.CheckConstraint(
            "native_launch_handle IS NULL OR status IN ('created', 'running')",
            name="ck_my_photo_liveness_native_launch_handle",
        ),
        sa.CheckConstraint(
            "(completion_idempotency_key IS NULL AND completion_outcome IS NULL) OR "
            "(completion_idempotency_key IS NOT NULL AND completion_outcome IN "
            "('completed', 'cancelled', 'expired', 'failed'))",
            name="ck_my_photo_liveness_completion",
        ),
        sa.CheckConstraint(
            "(provider_claim_token IS NULL) = (provider_claim_expires_at IS NULL)",
            name="ck_my_photo_liveness_provider_claim_shape",
        ),
        sa.CheckConstraint(
            "provider_claim_token IS NULL OR status IN ('creating', 'running')",
            name="ck_my_photo_liveness_provider_claim_status",
        ),
        sa.CheckConstraint(
            "(consumed_at IS NULL AND status IN ('creating', 'created', 'running')) OR "
            "(consumed_at IS NOT NULL AND status IN "
            "('completed', 'cancelled', 'expired', 'rejected', 'failed'))",
            name="ck_my_photo_liveness_single_use",
        ),
        sa.CheckConstraint(
            "(status IN ('creating', 'created', 'running') AND result_retryable IS NULL) OR "
            "(status IN ('completed', 'cancelled', 'expired', 'rejected', 'failed') "
            "AND result_retryable IS NOT NULL)",
            name="ck_my_photo_liveness_retryable_shape",
        ),
        sa.ForeignKeyConstraint(
            ["enrollment_id", "agency_id", "group_id"],
            [
                "my_photo_enrollments.id",
                "my_photo_enrollments.agency_id",
                "my_photo_enrollments.group_id",
            ],
            name="fk_my_photo_liveness_enrollment",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_liveness_scope"),
        sa.UniqueConstraint(
            "enrollment_id", "idempotency_key", name="uq_my_photo_liveness_idempotency"
        ),
    )
    op.create_index(
        "ix_my_photo_liveness_expiry",
        "my_photo_liveness_sessions",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_my_photo_liveness_provider_claim",
        "my_photo_liveness_sessions",
        ["status", "provider_claim_expires_at"],
    )
    op.create_index(
        "uq_my_photo_liveness_active_enrollment",
        "my_photo_liveness_sessions",
        ["enrollment_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('creating', 'created', 'running')"),
    )


def _create_search_runs() -> None:
    op.create_table(
        "my_photo_search_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enrollment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gallery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gallery_revision", sa.BigInteger(), nullable=False),
        sa.Column("face_index_version", sa.BigInteger(), nullable=False),
        sa.Column("enrollment_version", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("processed_face_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_face_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matched_asset_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("best_match_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("possible_match_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("checkpoint_cursor", sa.String(length=512), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stable_error_code", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('queued', 'searching', 'complete', 'failed', 'cancelled')",
            name="ck_my_photo_search_status",
        ),
        sa.CheckConstraint(
            "gallery_revision >= 1 AND face_index_version >= 1 AND enrollment_version >= 1",
            name="ck_my_photo_search_versions",
        ),
        sa.CheckConstraint(
            "processed_face_count >= 0 AND total_face_count >= 0 "
            "AND processed_face_count <= total_face_count AND matched_asset_count >= 0 "
            "AND matched_asset_count <= total_face_count "
            "AND best_match_count >= 0 AND possible_match_count >= 0 "
            "AND best_match_count + possible_match_count = matched_asset_count",
            name="ck_my_photo_search_progress",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20",
            name="ck_my_photo_search_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["enrollment_id", "passenger_identity_id", "agency_id", "group_id"],
            [
                "my_photo_enrollments.id",
                "my_photo_enrollments.passenger_identity_id",
                "my_photo_enrollments.agency_id",
                "my_photo_enrollments.group_id",
            ],
            name="fk_my_photo_search_enrollment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["gallery_id", "agency_id", "group_id"],
            [
                "my_photo_galleries.id",
                "my_photo_galleries.agency_id",
                "my_photo_galleries.group_id",
            ],
            name="fk_my_photo_search_gallery",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "passenger_identity_id",
            "agency_id",
            "group_id",
            name="uq_my_photo_search_scope",
        ),
        sa.UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_search_trip_scope"),
        sa.UniqueConstraint(
            "passenger_identity_id",
            "group_id",
            "idempotency_key",
            name="uq_my_photo_search_idempotency",
        ),
    )
    op.create_index(
        "ix_my_photo_search_passenger_current",
        "my_photo_search_runs",
        ["passenger_identity_id", "group_id", "gallery_revision", "created_at"],
    )
    op.create_index(
        "ix_my_photo_search_lease", "my_photo_search_runs", ["status", "lease_expires_at"]
    )


def _create_matches() -> None:
    op.create_table(
        "my_photo_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("search_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("face_occurrence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gallery_revision", sa.BigInteger(), nullable=False),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("display_tier", sa.String(length=16), nullable=False),
        sa.Column("match_config_version", sa.String(length=64), nullable=False),
        sa.Column("feedback", sa.String(length=16), server_default="none", nullable=False),
        sa.Column("feedback_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_rank", sa.BigInteger(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("similarity BETWEEN 0 AND 100", name="ck_my_photo_match_similarity"),
        sa.CheckConstraint("display_tier IN ('best', 'possible')", name="ck_my_photo_match_tier"),
        sa.CheckConstraint(
            "feedback IN ('none', 'this_is_me', 'not_me')",
            name="ck_my_photo_match_feedback",
        ),
        sa.CheckConstraint(
            "(active = true AND superseded_at IS NULL) OR "
            "(active = false AND superseded_at IS NOT NULL)",
            name="ck_my_photo_match_active",
        ),
        sa.ForeignKeyConstraint(
            ["search_run_id", "passenger_identity_id", "agency_id", "group_id"],
            [
                "my_photo_search_runs.id",
                "my_photo_search_runs.passenger_identity_id",
                "my_photo_search_runs.agency_id",
                "my_photo_search_runs.group_id",
            ],
            name="fk_my_photo_match_search",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id", "agency_id", "group_id"],
            [
                "my_photo_media_assets.id",
                "my_photo_media_assets.agency_id",
                "my_photo_media_assets.group_id",
            ],
            name="fk_my_photo_match_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["face_occurrence_id", "media_asset_id", "agency_id", "group_id"],
            [
                "my_photo_face_occurrences.id",
                "my_photo_face_occurrences.media_asset_id",
                "my_photo_face_occurrences.agency_id",
                "my_photo_face_occurrences.group_id",
            ],
            name="fk_my_photo_match_face",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_match_scope"),
        sa.UniqueConstraint(
            "search_run_id",
            "passenger_identity_id",
            "media_asset_id",
            name="uq_my_photo_match_run_asset",
        ),
    )
    op.create_index(
        "uq_my_photo_match_active_asset",
        "my_photo_matches",
        ["passenger_identity_id", "media_asset_id"],
        unique=True,
        postgresql_where=sa.text("active = true"),
        sqlite_where=sa.text("active = true"),
    )
    op.create_index(
        "ix_my_photo_match_page",
        "my_photo_matches",
        [
            "passenger_identity_id",
            "gallery_revision",
            "active",
            "display_tier",
            "sort_rank",
            "media_asset_id",
        ],
    )


def _create_jobs() -> None:
    op.create_table(
        "my_photo_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gallery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("search_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="queued", nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("target_revision", sa.BigInteger(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("checkpoint_cursor", sa.String(length=512), nullable=True),
        sa.Column("processed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("succeeded_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stable_error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail", sa.String(length=512), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "job_type IN ('index_gallery', 'generate_variants', 'search_passenger', "
            "'prepare_media', 'refresh_searches')",
            name="ck_my_photo_job_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'retrying', 'succeeded', 'cancelled', 'failed')",
            name="ck_my_photo_job_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20 "
            "AND processed_count >= 0 AND total_count >= 0 AND processed_count <= total_count "
            "AND succeeded_count >= 0 AND failed_count >= 0 "
            "AND succeeded_count + failed_count <= processed_count",
            name="ck_my_photo_job_counts",
        ),
        sa.CheckConstraint(
            "request_fingerprint IS NULL OR "
            "(length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint))",
            name="ck_my_photo_job_request_fingerprint",
        ),
        sa.CheckConstraint(
            "(job_type IN ('index_gallery', 'refresh_searches') "
            "AND media_asset_id IS NULL AND search_run_id IS NULL "
            "AND target_revision IS NOT NULL) OR "
            "(job_type IN ('generate_variants', 'prepare_media') "
            "AND media_asset_id IS NOT NULL AND search_run_id IS NULL "
            "AND target_revision IS NULL) OR "
            "(job_type = 'search_passenger' AND media_asset_id IS NULL "
            "AND search_run_id IS NOT NULL AND target_revision IS NULL)",
            name="ck_my_photo_job_target",
        ),
        sa.CheckConstraint(
            "target_revision IS NULL OR target_revision >= 1",
            name="ck_my_photo_job_target_revision",
        ),
        sa.ForeignKeyConstraint(
            ["gallery_id", "agency_id", "group_id"],
            [
                "my_photo_galleries.id",
                "my_photo_galleries.agency_id",
                "my_photo_galleries.group_id",
            ],
            name="fk_my_photo_job_gallery",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id", "agency_id", "group_id"],
            [
                "my_photo_media_assets.id",
                "my_photo_media_assets.agency_id",
                "my_photo_media_assets.group_id",
            ],
            name="fk_my_photo_job_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["search_run_id", "agency_id", "group_id"],
            [
                "my_photo_search_runs.id",
                "my_photo_search_runs.agency_id",
                "my_photo_search_runs.group_id",
            ],
            name="fk_my_photo_job_search",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_job_scope"),
        sa.UniqueConstraint(
            "gallery_id", "job_type", "idempotency_key", name="uq_my_photo_job_idempotency"
        ),
    )
    op.create_index(
        "ix_my_photo_job_claim",
        "my_photo_jobs",
        ["job_type", "status", "next_attempt_at", "created_at"],
    )
    op.create_index("ix_my_photo_job_lease", "my_photo_jobs", ["status", "lease_expires_at"])


def _create_delivery_authorizations() -> None:
    op.create_table(
        "my_photo_delivery_authorizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passenger_submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gc_group_access_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quality", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("delivery_version", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column("provider_authorization_reference", sa.String(length=512), nullable=True),
        sa.Column("transport", sa.String(length=32), server_default="unavailable", nullable=False),
        sa.Column("claim_token", sa.String(length=64), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("content_type", sa.String(length=64), nullable=True),
        sa.Column("supports_ranges", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stable_error_code", sa.String(length=64), nullable=True),
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
            "quality IN ('original', 'optimized')", name="ck_my_photo_delivery_quality"
        ),
        sa.CheckConstraint(
            "content_type IS NULL OR content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_my_photo_delivery_content_type",
        ),
        sa.CheckConstraint(
            "status IN ('authorizing', 'preparing', 'available', 'expired', 'failed', 'cancelled')",
            name="ck_my_photo_delivery_status",
        ),
        sa.CheckConstraint(
            "expected_size_bytes IS NULL OR expected_size_bytes BETWEEN 1 AND 209715200",
            name="ck_my_photo_delivery_size",
        ),
        sa.CheckConstraint(
            "checksum_sha256 IS NULL OR "
            "(length(checksum_sha256) = 64 AND checksum_sha256 = lower(checksum_sha256))",
            name="ck_my_photo_delivery_checksum",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)",
            name="ck_my_photo_delivery_fingerprint",
        ),
        sa.CheckConstraint(
            "transport IN ('unavailable', 'development_fixture', 'direct_object_storage')",
            name="ck_my_photo_delivery_transport",
        ),
        sa.CheckConstraint(
            "(status = 'authorizing' AND claim_token IS NOT NULL AND claim_expires_at IS NOT NULL) "
            "OR (status != 'authorizing' AND claim_token IS NULL AND claim_expires_at IS NULL)",
            name="ck_my_photo_delivery_claim",
        ),
        sa.CheckConstraint(
            "(status = 'available' AND provider_authorization_reference IS NOT NULL "
            "AND expected_size_bytes IS NOT NULL AND checksum_sha256 IS NOT NULL "
            "AND content_type IS NOT NULL AND expires_at IS NOT NULL "
            "AND transport != 'unavailable') OR "
            "(status != 'available' AND provider_authorization_reference IS NULL "
            "AND expected_size_bytes IS NULL AND checksum_sha256 IS NULL "
            "AND content_type IS NULL AND expires_at IS NULL "
            "AND supports_ranges = false AND transport = 'unavailable')",
            name="ck_my_photo_delivery_available",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id", "agency_id", "group_id"],
            [
                "my_photo_media_assets.id",
                "my_photo_media_assets.agency_id",
                "my_photo_media_assets.group_id",
            ],
            name="fk_my_photo_delivery_asset",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "passenger_identity_id",
                "gc_group_access_id",
                "agency_id",
                "group_id",
                "passenger_submission_id",
            ],
            [
                "mobile_passenger_identities.id",
                "mobile_passenger_identities.gc_group_access_id",
                "mobile_passenger_identities.agency_id",
                "mobile_passenger_identities.group_id",
                "mobile_passenger_identities.passenger_submission_id",
            ],
            name="fk_my_photo_delivery_passenger",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "agency_id", "group_id", name="uq_my_photo_delivery_scope"),
        sa.UniqueConstraint(
            "passenger_identity_id",
            "media_asset_id",
            "quality",
            "idempotency_key",
            name="uq_my_photo_delivery_idempotency",
        ),
    )
    op.create_index(
        "ix_my_photo_delivery_expiry",
        "my_photo_delivery_authorizations",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_table("my_photo_delivery_authorizations")
    op.drop_table("my_photo_jobs")
    op.drop_table("my_photo_matches")
    op.drop_table("my_photo_search_runs")
    op.drop_table("my_photo_liveness_sessions")
    op.drop_table("my_photo_enrollments")
    op.drop_table("my_photo_face_occurrences")
    op.drop_table("my_photo_asset_variants")
    op.drop_table("my_photo_media_assets")
    op.drop_table("my_photo_gallery_manifest_batches")
    op.drop_index("uq_my_photo_manifest_active_revision", table_name="my_photo_gallery_manifests")
    op.drop_index("ix_my_photo_manifest_status", table_name="my_photo_gallery_manifests")
    op.drop_table("my_photo_gallery_manifests")
    op.drop_table("my_photo_galleries")
