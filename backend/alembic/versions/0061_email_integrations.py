"""Add tenant-scoped email integration persistence.

Revision ID: 0061_email_integrations
Revises: 0060_fine_rotation
Create Date: 2026-07-28
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0061_email_integrations"
down_revision = "0060_fine_rotation"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "email_connections",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("provider_account_id", sa.String(length=512), nullable=False),
        sa.Column("email_address", sa.String(length=320), nullable=False),
        sa.Column("normalized_email_address", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "sync_state",
            sa.String(length=24),
            server_default=sa.text("'idle'"),
            nullable=False,
        ),
        sa.Column(
            "scopes",
            _JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("access_token_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("refresh_token_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column(
            "token_key_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_cursor", sa.Text(), nullable=True),
        sa.Column("watch_resource_id", sa.String(length=255), nullable=True),
        sa.Column("watch_expiration_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_lease_token", sa.String(length=128), nullable=True),
        sa.Column("sync_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sync_generation",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("next_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", _UUID, nullable=True),
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
            "provider IN ('gmail', 'outlook')",
            name="ck_email_connections_provider",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'pending', 'active', 'paused', 'expired', 'failing', "
            "'disconnecting', 'disconnected'"
            ")",
            name="ck_email_connections_status",
        ),
        sa.CheckConstraint(
            "sync_state IN ('idle', 'queued', 'running', 'retry_wait', 'blocked')",
            name="ck_email_connections_sync_state",
        ),
        sa.CheckConstraint(
            "token_key_version >= 1",
            name="ck_email_connections_key_version",
        ),
        sa.CheckConstraint(
            "sync_generation >= 0",
            name="ck_email_connections_sync_generation",
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_email_connections_failure_count",
        ),
        sa.CheckConstraint(
            "(sync_lease_token IS NULL) = (sync_lease_expires_at IS NULL)",
            name="ck_email_connections_sync_lease_pair",
        ),
        sa.CheckConstraint(
            "access_token_ciphertext IS NULL OR length(access_token_ciphertext) > 0",
            name="ck_email_connections_access_token_nonempty",
        ),
        sa.CheckConstraint(
            "refresh_token_ciphertext IS NULL OR length(refresh_token_ciphertext) > 0",
            name="ck_email_connections_refresh_token_nonempty",
        ),
        sa.CheckConstraint(
            "status != 'disconnected' OR disconnected_at IS NOT NULL",
            name="ck_email_connections_disconnected_at",
        ),
        sa.CheckConstraint(
            "normalized_email_address = lower(trim(email_address))",
            name="ck_email_connections_normalized_email",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "agency_id",
            name="uq_email_connections_id_agency",
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_account_id",
            name="uq_email_connections_provider_account",
        ),
        sa.UniqueConstraint(
            "agency_id",
            "provider",
            "normalized_email_address",
            name="uq_email_connections_agency_provider_email",
        ),
    )
    op.create_index(
        "ix_email_connections_agency_status",
        "email_connections",
        ["agency_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_email_connections_sync_due",
        "email_connections",
        ["status", "next_sync_at", "sync_lease_expires_at"],
        unique=False,
    )

    op.create_table(
        "email_oauth_states",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("user_id", _UUID, nullable=False),
        sa.Column("connection_id", _UUID, nullable=True),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("nonce_hash", sa.String(length=64), nullable=True),
        sa.Column("code_verifier_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column(
            "key_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "requested_scopes",
            _JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("return_path", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('gmail', 'outlook')",
            name="ck_email_oauth_states_provider",
        ),
        sa.CheckConstraint(
            "length(state_hash) = 64",
            name="ck_email_oauth_states_state_hash",
        ),
        sa.CheckConstraint(
            "nonce_hash IS NULL OR length(nonce_hash) = 64",
            name="ck_email_oauth_states_nonce_hash",
        ),
        sa.CheckConstraint(
            "length(code_verifier_ciphertext) > 0",
            name="ck_email_oauth_states_verifier_nonempty",
        ),
        sa.CheckConstraint(
            "key_version >= 1",
            name="ck_email_oauth_states_key_version",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_email_oauth_states_expiry",
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name="ck_email_oauth_states_consumed_at",
        ),
        sa.CheckConstraint(
            "return_path IS NULL OR ("
            "substr(return_path, 1, 1) = '/' AND substr(return_path, 1, 2) != '//'"
            ")",
            name="ck_email_oauth_states_return_path",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "agency_id"],
            ["email_connections.id", "email_connections.agency_id"],
            name="fk_email_oauth_states_connection_agency",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "state_hash",
            name="uq_email_oauth_states_state_hash",
        ),
    )
    op.create_index(
        "ix_email_oauth_states_expiry",
        "email_oauth_states",
        ["expires_at", "consumed_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_oauth_states_agency_provider",
        "email_oauth_states",
        ["agency_id", "provider", "created_at"],
        unique=False,
    )

    op.create_table(
        "email_messages",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("connection_id", _UUID, nullable=False),
        sa.Column("provider_message_id", sa.String(length=512), nullable=False),
        sa.Column("thread_id", sa.String(length=512), nullable=True),
        sa.Column("provider_history_id", sa.String(length=255), nullable=True),
        sa.Column("internet_message_id", sa.String(length=998), nullable=True),
        sa.Column("sender_address", sa.String(length=320), nullable=True),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column(
            "recipients_json",
            _JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body_excerpt", sa.Text(), nullable=True),
        sa.Column(
            "label_ids",
            _JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "has_attachments",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "relevance_status",
            sa.String(length=24),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("relevance_confidence", sa.Float(), nullable=True),
        sa.Column(
            "evidence_json",
            _JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "processing_status",
            sa.String(length=32),
            server_default=sa.text("'discovered'"),
            nullable=False,
        ),
        sa.Column(
            "artifact_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "processed_artifact_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "review_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("group_id", _UUID, nullable=True),
        sa.Column(
            "ai_used",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
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
            "relevance_status IN ('pending', 'relevant', 'possible', 'ignored', 'failed')",
            name="ck_email_messages_relevance_status",
        ),
        sa.CheckConstraint(
            "processing_status IN ("
            "'discovered', 'queued', 'processing', 'completed', "
            "'partially_completed', 'review_required', 'failed', 'ignored'"
            ")",
            name="ck_email_messages_processing_status",
        ),
        sa.CheckConstraint(
            "relevance_confidence IS NULL OR "
            "(relevance_confidence >= 0 AND relevance_confidence <= 1)",
            name="ck_email_messages_relevance_confidence",
        ),
        sa.CheckConstraint(
            "artifact_count >= 0 AND processed_artifact_count >= 0 AND review_count >= 0",
            name="ck_email_messages_counts",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["client_groups.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "agency_id"],
            ["email_connections.id", "email_connections.agency_id"],
            name="fk_email_messages_connection_agency",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "connection_id",
            "provider_message_id",
            name="uq_email_messages_connection_provider_message",
        ),
        sa.UniqueConstraint(
            "id",
            "agency_id",
            name="uq_email_messages_id_agency",
        ),
        sa.UniqueConstraint(
            "id",
            "connection_id",
            "agency_id",
            name="uq_email_messages_id_connection_agency",
        ),
    )
    op.create_index(
        "ix_email_messages_agency_received",
        "email_messages",
        ["agency_id", "received_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_messages_agency_processing",
        "email_messages",
        ["agency_id", "processing_status", "received_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_messages_connection_thread",
        "email_messages",
        ["connection_id", "thread_id"],
        unique=False,
    )

    op.create_table(
        "email_artifacts",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("message_id", _UUID, nullable=False),
        sa.Column("provider_artifact_id", sa.String(length=768), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("provider_attachment_id", sa.String(length=768), nullable=True),
        sa.Column("provider_part_id", sa.String(length=255), nullable=True),
        sa.Column("filename", sa.String(length=500), nullable=True),
        sa.Column("declared_content_type", sa.String(length=255), nullable=True),
        sa.Column("verified_content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256_digest", sa.String(length=64), nullable=True),
        sa.Column("storage_key", sa.String(length=1024), nullable=True),
        sa.Column("source_url_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("source_url_encryption_key_version", sa.Integer(), nullable=True),
        sa.Column(
            "retrieval_status",
            sa.String(length=24),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "processing_status",
            sa.String(length=24),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "detected_type",
            sa.String(length=32),
            server_default=sa.text("'unknown'"),
            nullable=False,
        ),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column("group_id", _UUID, nullable=True),
        sa.Column("passenger_id", _UUID, nullable=True),
        sa.Column("duplicate_of_id", _UUID, nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default=sa.text("3"),
            nullable=False,
        ),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
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
            "kind IN ('attachment', 'inline', 'direct_link', 'cloud_link', 'portal_link')",
            name="ck_email_artifacts_source_kind",
        ),
        sa.CheckConstraint(
            "retrieval_status IN ("
            "'pending', 'retrieving', 'retrieved', 'blocked', 'failed', 'ignored'"
            ")",
            name="ck_email_artifacts_retrieval_status",
        ),
        sa.CheckConstraint(
            "processing_status IN ("
            "'pending', 'queued', 'processing', 'completed', 'review_required', "
            "'duplicate', 'failed', 'ignored'"
            ")",
            name="ck_email_artifacts_processing_status",
        ),
        sa.CheckConstraint(
            "detected_type IN ('unknown', 'visa', 'flight_ticket', 'passport', 'other')",
            name="ck_email_artifacts_detected_type",
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_email_artifacts_size",
        ),
        sa.CheckConstraint(
            "sha256_digest IS NULL OR length(sha256_digest) = 64",
            name="ck_email_artifacts_sha256",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts",
            name="ck_email_artifacts_attempts",
        ),
        sa.CheckConstraint(
            "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
            name="ck_email_artifacts_lease_pair",
        ),
        sa.CheckConstraint(
            "(source_url_ciphertext IS NULL) = (source_url_encryption_key_version IS NULL)",
            name="ck_email_artifacts_source_url_key_pair",
        ),
        sa.CheckConstraint(
            "source_url_ciphertext IS NULL OR length(source_url_ciphertext) > 0",
            name="ck_email_artifacts_source_url_nonempty",
        ),
        sa.CheckConstraint(
            "source_url_encryption_key_version IS NULL OR source_url_encryption_key_version >= 1",
            name="ck_email_artifacts_source_url_key_version",
        ),
        sa.CheckConstraint(
            "duplicate_of_id IS NULL OR duplicate_of_id != id",
            name="ck_email_artifacts_not_self_duplicate",
        ),
        sa.CheckConstraint(
            "match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)",
            name="ck_email_artifacts_match_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["client_groups.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["passenger_id"],
            ["passport_submissions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id", "agency_id"],
            ["email_messages.id", "email_messages.agency_id"],
            name="fk_email_artifacts_message_agency",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_id", "agency_id"],
            ["email_artifacts.id", "email_artifacts.agency_id"],
            name="fk_email_artifacts_duplicate_agency",
            ondelete="NO ACTION",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id",
            "provider_artifact_id",
            name="uq_email_artifacts_message_provider_artifact",
        ),
        sa.UniqueConstraint(
            "id",
            "agency_id",
            name="uq_email_artifacts_id_agency",
        ),
        sa.UniqueConstraint(
            "id",
            "message_id",
            "agency_id",
            name="uq_email_artifacts_id_message_agency",
        ),
    )
    op.create_index(
        "ix_email_artifacts_agency_processing",
        "email_artifacts",
        ["agency_id", "processing_status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_artifacts_retry_due",
        "email_artifacts",
        ["retrieval_status", "next_retry_at", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_artifacts_agency_sha256",
        "email_artifacts",
        ["agency_id", "sha256_digest"],
        unique=False,
    )

    op.create_table(
        "email_artifact_documents",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("artifact_id", _UUID, nullable=False),
        sa.Column("distributed_document_id", _UUID, nullable=False),
        sa.Column("result_type", sa.String(length=32), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column(
            "match_evidence",
            _JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "result_type IN ("
            "'created', 'existing_duplicate', 'revision_candidate', 'conflict_candidate'"
            ")",
            name="ck_email_artifact_documents_result_type",
        ),
        sa.CheckConstraint(
            "match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)",
            name="ck_email_artifact_documents_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["distributed_document_id"],
            ["distributed_documents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "agency_id"],
            ["email_artifacts.id", "email_artifacts.agency_id"],
            name="fk_email_artifact_documents_artifact_agency",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_id",
            "distributed_document_id",
            name="uq_email_artifact_documents_artifact_document",
        ),
    )
    op.create_index(
        "ix_email_artifact_documents_agency_document",
        "email_artifact_documents",
        ["agency_id", "distributed_document_id"],
        unique=False,
    )

    op.create_table(
        "email_review_items",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("message_id", _UUID, nullable=False),
        sa.Column("artifact_id", _UUID, nullable=True),
        sa.Column("review_type", sa.String(length=40), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column("proposed_action", sa.String(length=80), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "evidence",
            _JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "conflicts",
            _JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "alternatives",
            _JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "proposed_payload",
            _JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("candidate_group_id", _UUID, nullable=True),
        sa.Column("candidate_passenger_id", _UUID, nullable=True),
        sa.Column("selected_group_id", _UUID, nullable=True),
        sa.Column("selected_passenger_id", _UUID, nullable=True),
        sa.Column(
            "revision",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("resolution_request_id", _UUID, nullable=True),
        sa.Column("assigned_to_user_id", _UUID, nullable=True),
        sa.Column("resolved_by_user_id", _UUID, nullable=True),
        sa.Column("resolution_code", sa.String(length=80), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("deferred_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "review_type IN ("
            "'relevance', 'retrieval', 'group_match', 'passenger_match', "
            "'document_conflict', 'possible_revision', 'traveller_replacement', "
            "'contact_change', 'processing_failure'"
            ")",
            name="ck_email_review_items_review_type",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'deferred', 'resolved', 'rejected', 'cancelled')",
            name="ck_email_review_items_status",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_email_review_items_confidence",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_email_review_items_revision",
        ),
        sa.CheckConstraint(
            "(status IN ('resolved', 'rejected', 'cancelled') "
            "AND resolved_at IS NOT NULL) OR "
            "(status IN ('open', 'deferred') AND resolved_at IS NULL)",
            name="ck_email_review_items_resolution_state",
        ),
        sa.CheckConstraint(
            "status != 'deferred' OR deferred_until IS NOT NULL",
            name="ck_email_review_items_deferred_until",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_group_id"],
            ["client_groups.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_passenger_id"],
            ["passport_submissions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["selected_group_id"],
            ["client_groups.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["selected_passenger_id"],
            ["passport_submissions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id", "agency_id"],
            ["email_messages.id", "email_messages.agency_id"],
            name="fk_email_review_items_message_agency",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "message_id", "agency_id"],
            [
                "email_artifacts.id",
                "email_artifacts.message_id",
                "email_artifacts.agency_id",
            ],
            name="fk_email_review_items_artifact_message_agency",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "agency_id",
            name="uq_email_review_items_id_agency",
        ),
        sa.UniqueConstraint(
            "id",
            "message_id",
            "agency_id",
            name="uq_email_review_items_id_message_agency",
        ),
        sa.UniqueConstraint(
            "resolution_request_id",
            name="uq_email_review_items_resolution_request",
        ),
    )
    op.create_index(
        "uq_email_review_items_active_message",
        "email_review_items",
        ["agency_id", "message_id", "review_type"],
        unique=True,
        postgresql_where=sa.text("artifact_id IS NULL AND status IN ('open', 'deferred')"),
    )
    op.create_index(
        "uq_email_review_items_active_artifact",
        "email_review_items",
        ["agency_id", "artifact_id", "review_type"],
        unique=True,
        postgresql_where=sa.text("artifact_id IS NOT NULL AND status IN ('open', 'deferred')"),
    )
    op.create_index(
        "ix_email_review_items_agency_queue",
        "email_review_items",
        ["agency_id", "status", "created_at"],
        unique=False,
    )

    op.create_table(
        "email_activity_events",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("agency_id", _UUID, nullable=False),
        sa.Column("connection_id", _UUID, nullable=False),
        sa.Column("message_id", _UUID, nullable=True),
        sa.Column("artifact_id", _UUID, nullable=True),
        sa.Column("review_item_id", _UUID, nullable=True),
        sa.Column("event_key", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column(
            "actor_type",
            sa.String(length=16),
            server_default=sa.text("'system'"),
            nullable=False,
        ),
        sa.Column("actor_user_id", _UUID, nullable=True),
        sa.Column("summary_code", sa.String(length=100), nullable=False),
        sa.Column(
            "details",
            _JSONB,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "ai_used",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("ai_provider", sa.String(length=80), nullable=True),
        sa.Column("ai_model", sa.String(length=128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("changed_entity_type", sa.String(length=80), nullable=True),
        sa.Column("changed_entity_id", _UUID, nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "stage IN ('info', 'success', 'warning', 'failure')",
            name="ck_email_activity_events_stage",
        ),
        sa.CheckConstraint(
            "actor_type IN ('system', 'user', 'provider')",
            name="ck_email_activity_events_actor_type",
        ),
        sa.CheckConstraint(
            "actor_type = 'user' OR actor_user_id IS NULL",
            name="ck_email_activity_events_actor",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_email_activity_events_confidence",
        ),
        sa.CheckConstraint(
            "artifact_id IS NULL OR message_id IS NOT NULL",
            name="ck_email_activity_events_artifact_message",
        ),
        sa.CheckConstraint(
            "review_item_id IS NULL OR message_id IS NOT NULL",
            name="ck_email_activity_events_review_message",
        ),
        sa.CheckConstraint(
            "ai_used OR (ai_provider IS NULL AND ai_model IS NULL)",
            name="ck_email_activity_events_ai_metadata",
        ),
        sa.ForeignKeyConstraint(
            ["agency_id"],
            ["agencies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "agency_id"],
            ["email_connections.id", "email_connections.agency_id"],
            name="fk_email_activity_events_connection_agency",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id", "connection_id", "agency_id"],
            [
                "email_messages.id",
                "email_messages.connection_id",
                "email_messages.agency_id",
            ],
            name="fk_email_activity_events_message_connection_agency",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id", "message_id", "agency_id"],
            [
                "email_artifacts.id",
                "email_artifacts.message_id",
                "email_artifacts.agency_id",
            ],
            name="fk_email_activity_events_artifact_message_agency",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["review_item_id", "message_id", "agency_id"],
            [
                "email_review_items.id",
                "email_review_items.message_id",
                "email_review_items.agency_id",
            ],
            name="fk_email_activity_events_review_message_agency",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "agency_id",
            "event_key",
            name="uq_email_activity_events_agency_event_key",
        ),
    )
    op.create_index(
        "ix_email_activity_events_agency_occurred",
        "email_activity_events",
        ["agency_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_email_activity_events_message_occurred",
        "email_activity_events",
        ["message_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("email_activity_events")
    op.drop_table("email_review_items")
    op.drop_table("email_artifact_documents")
    op.drop_table("email_artifacts")
    op.drop_table("email_messages")
    op.drop_table("email_oauth_states")
    op.drop_table("email_connections")
