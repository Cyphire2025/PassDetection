"""Explicit authored notification batches and native APNs registration scope.

Revision ID: 0097_authored_notifications
Revises: 0096_mobile_phone_lookup

Frozen DDL intentionally does not import runtime models. Existing announcement
feed/history remains; only definitely unsent legacy phone attempts are cancelled.
"""

from alembic import op
import sqlalchemy as sa

revision = "0097_authored_notifications"
down_revision = "0096_mobile_phone_lookup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE gc_notification_drafts (
	id UUID NOT NULL,
	agency_id UUID NOT NULL,
	title VARCHAR(100) NOT NULL,
	body VARCHAR(240) NOT NULL,
	audience VARCHAR(24) NOT NULL,
	group_ids JSONB DEFAULT '[]' NOT NULL,
	group_names JSONB DEFAULT '[]' NOT NULL,
	revision INTEGER DEFAULT '1' NOT NULL,
	status VARCHAR(16) DEFAULT 'draft' NOT NULL,
	created_by_user_id UUID,
	updated_by_user_id UUID,
	last_sent_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_gc_notification_draft_scope UNIQUE (id, agency_id),
	CONSTRAINT ck_gc_notification_draft_revision CHECK (revision >= 1),
	CONSTRAINT ck_gc_notification_draft_status CHECK (status IN ('draft', 'sent')),
	CONSTRAINT ck_gc_notification_draft_audience CHECK (audience IN ('all_active_trips', 'selected_groups')),
	CONSTRAINT ck_gc_notification_draft_content CHECK (length(trim(title)) BETWEEN 1 AND 100 AND length(trim(body)) BETWEEN 1 AND 240),
	FOREIGN KEY(agency_id) REFERENCES agencies (id) ON DELETE CASCADE,
	FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL,
	FOREIGN KEY(updated_by_user_id) REFERENCES users (id) ON DELETE SET NULL
)
    """)
    op.execute(
        "CREATE INDEX ix_gc_notification_draft_page ON gc_notification_drafts (agency_id, id)"
    )
    op.execute("""
CREATE TABLE gc_notification_batches (
	id UUID NOT NULL,
	agency_id UUID NOT NULL,
	draft_id UUID NOT NULL,
	draft_revision INTEGER NOT NULL,
	request_id UUID NOT NULL,
	request_fingerprint VARCHAR(64) NOT NULL,
	title VARCHAR(100) NOT NULL,
	body VARCHAR(240) NOT NULL,
	audience VARCHAR(24) NOT NULL,
	group_ids JSONB NOT NULL,
	group_names JSONB NOT NULL,
	role_counts JSONB NOT NULL,
	created_by_user_id UUID,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_gc_notification_batch_scope UNIQUE (id, agency_id),
	CONSTRAINT uq_gc_notification_batch_request UNIQUE (agency_id, request_id),
	CONSTRAINT fk_gc_notification_batch_draft FOREIGN KEY(draft_id, agency_id) REFERENCES gc_notification_drafts (id, agency_id) ON DELETE CASCADE,
	CONSTRAINT ck_gc_notification_batch_request CHECK (draft_revision >= 1 AND length(request_fingerprint) = 64),
	CONSTRAINT ck_gc_notification_batch_expiry CHECK (expires_at > created_at),
	CONSTRAINT ck_gc_notification_batch_audience CHECK (audience IN ('all_active_trips', 'selected_groups')),
	CONSTRAINT ck_gc_notification_batch_content CHECK (length(trim(title)) BETWEEN 1 AND 100 AND length(trim(body)) BETWEEN 1 AND 240),
	FOREIGN KEY(agency_id) REFERENCES agencies (id) ON DELETE CASCADE,
	FOREIGN KEY(created_by_user_id) REFERENCES users (id) ON DELETE SET NULL
)
    """)
    op.execute(
        "CREATE INDEX ix_gc_notification_batch_page ON gc_notification_batches (agency_id, id)"
    )
    op.execute("""
CREATE TABLE gc_notification_recipients (
	id UUID NOT NULL,
	agency_id UUID NOT NULL,
	batch_id UUID NOT NULL,
	recipient_type VARCHAR(24) NOT NULL,
	person_key VARCHAR(80) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_gc_notification_recipient_scope UNIQUE (id, agency_id),
	CONSTRAINT uq_gc_notification_batch_person UNIQUE (batch_id, person_key),
	CONSTRAINT fk_gc_notification_recipient_batch FOREIGN KEY(batch_id, agency_id) REFERENCES gc_notification_batches (id, agency_id) ON DELETE CASCADE,
	CONSTRAINT ck_gc_notification_recipient_type CHECK (recipient_type IN ('passenger', 'client_manager', 'coordinator'))
)
    """)
    op.execute(
        "CREATE INDEX ix_gc_notification_recipient_batch ON gc_notification_recipients (agency_id, batch_id)"
    )
    op.execute("""
CREATE TABLE gc_notification_recipient_grants (
	id UUID NOT NULL,
	agency_id UUID NOT NULL,
	recipient_id UUID NOT NULL,
	group_id UUID NOT NULL,
	gc_group_access_id UUID NOT NULL,
	principal_id UUID NOT NULL,
	access_generation INTEGER NOT NULL,
	identity_claim_generation INTEGER,
	PRIMARY KEY (id),
	CONSTRAINT fk_gc_notification_grant_recipient FOREIGN KEY(recipient_id, agency_id) REFERENCES gc_notification_recipients (id, agency_id) ON DELETE CASCADE,
	CONSTRAINT uq_gc_notification_recipient_grant UNIQUE (recipient_id, group_id, principal_id),
	CONSTRAINT ck_gc_notification_grant_generations CHECK (access_generation >= 0 AND (identity_claim_generation IS NULL OR identity_claim_generation >= 0))
)
    """)
    op.execute(
        "CREATE INDEX ix_gc_notification_grant_principal ON gc_notification_recipient_grants (agency_id, principal_id, recipient_id)"
    )
    op.add_column(
        "mobile_push_registrations", sa.Column("apns_environment", sa.String(11), nullable=True)
    )
    op.create_check_constraint(
        "ck_mobile_push_apns_environment",
        "mobile_push_registrations",
        "apns_environment IS NULL OR apns_environment IN ('development', 'production')",
    )
    op.add_column(
        "mobile_notifications", sa.Column("authored_recipient_id", sa.UUID(), nullable=True)
    )
    op.add_column(
        "mobile_notifications",
        sa.Column("next_push_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_mobile_notification_push_due",
        "mobile_notifications",
        ["status", "next_push_attempt_at", "id"],
    )
    op.create_foreign_key(
        "fk_mobile_notification_authored_recipient",
        "mobile_notifications",
        "gc_notification_recipients",
        ["authored_recipient_id", "agency_id"],
        ["id", "agency_id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_mobile_notification_authored_recipient",
        "mobile_notifications",
        ["authored_recipient_id"],
    )
    op.drop_constraint(
        "ck_mobile_notification_recipient_type", "mobile_notifications", type_="check"
    )
    op.create_check_constraint(
        "ck_mobile_notification_recipient_type",
        "mobile_notifications",
        "recipient_type IN ('passenger', 'client_manager', 'coordinator', 'authored')",
    )
    op.drop_constraint(
        "ck_mobile_notification_recipient_shape", "mobile_notifications", type_="check"
    )
    op.create_check_constraint(
        "ck_mobile_notification_recipient_shape",
        "mobile_notifications",
        "(recipient_type = 'passenger' AND recipient_passenger_identity_id IS NOT NULL AND recipient_user_id IS NULL AND authored_recipient_id IS NULL) OR (recipient_type IN ('client_manager', 'coordinator') AND recipient_user_id IS NOT NULL AND recipient_passenger_identity_id IS NULL AND authored_recipient_id IS NULL) OR (recipient_type = 'authored' AND authored_recipient_id IS NOT NULL AND recipient_user_id IS NULL AND recipient_passenger_identity_id IS NULL AND group_id IS NULL AND gc_group_access_id IS NULL)",
    )
    op.create_check_constraint(
        "ck_mobile_notification_authored_type",
        "mobile_notifications",
        "(notification_type = 'gc_alert') = (authored_recipient_id IS NOT NULL)",
    )
    op.execute(
        "UPDATE mobile_push_deliveries SET status = 'cancelled', last_error_code = 'announcement_in_app_only', updated_at = CURRENT_TIMESTAMP WHERE status = 'retry' AND provider_ticket_id IS NULL AND notification_id IN (SELECT id FROM mobile_notifications WHERE notification_type = 'group_announcement')"
    )
    op.execute(
        "UPDATE mobile_push_deliveries SET status = 'unknown', last_error_code = 'provider_outcome_unknown', updated_at = CURRENT_TIMESTAMP WHERE status = 'submitting' AND provider_ticket_id IS NULL AND notification_id IN (SELECT id FROM mobile_notifications WHERE notification_type = 'group_announcement')"
    )


def downgrade() -> None:
    # An older worker could send historical announcement queues again. Keep both
    # audit data and the dispatch contract until an explicit forward migration.
    raise RuntimeError(
        "Authored notification history and in-app-only announcements require schema0097; downgrade refused"
    )
