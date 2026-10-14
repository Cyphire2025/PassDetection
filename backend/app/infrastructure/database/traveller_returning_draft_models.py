"""Isolated 24-hour drafts; rows never represent accepted traveller history."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow
from app.infrastructure.database.traveller_model_support import (
    company_scope,
    document_scope,
    group_scope,
    record_scope,
)


class DraftRecord:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, server_default=text("CURRENT_TIMESTAMP"))


class TravellerReturningDraftModel(DraftRecord, Base):
    __tablename__ = "traveller_returning_drafts"
    __table_args__ = (
        company_scope("returning_draft"), group_scope("returning_draft"),
        document_scope("returning_draft"), record_scope("returning_draft"),
        UniqueConstraint("secret_hash", name="uq_returning_draft_secret"),
        UniqueConstraint("id", "agency_id", name="uq_returning_draft_tenant"),
        CheckConstraint("mode IN ('returning','fresh')", name="ck_returning_draft_mode"),
        CheckConstraint("(mode = 'returning' AND company_id IS NOT NULL AND traveller_id IS NOT NULL AND passport_id IS NOT NULL AND document_revision_id IS NOT NULL) OR (mode = 'fresh' AND traveller_id IS NULL AND passport_id IS NULL AND document_revision_id IS NULL AND upload_session_hash IS NOT NULL)", name="ck_returning_draft_authority"),
        CheckConstraint("status IN ('active','submitted','expired')", name="ck_returning_draft_status"),
        CheckConstraint("revision >= 1 AND fields_revision >= 1", name="ck_returning_draft_revision"),
        CheckConstraint("expires_at > created_at", name="ck_returning_draft_expiry"),
        Index("ix_returning_draft_expiry", "status", "expires_at", "id"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="returning")
    upload_session_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    traveller_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    passport_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    document_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fields_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    requirements_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_version: Mapped[str] = mapped_column(String(64), nullable=False)
    last_save_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_save_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_contact_claim_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    verified_phone_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_phone_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contact_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_version: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    completion_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    participation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_submission_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    result_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TravellerDraftAssetModel(DraftRecord, Base):
    __tablename__ = "traveller_draft_assets"
    __table_args__ = (
        ForeignKeyConstraint(["draft_id", "agency_id", "company_id"], ["traveller_returning_drafts.id", "traveller_returning_drafts.agency_id", "traveller_returning_drafts.company_id"], name="fk_returning_asset_draft_scope", ondelete="RESTRICT"),
        ForeignKeyConstraint(["draft_id", "agency_id"], ["traveller_returning_drafts.id", "traveller_returning_drafts.agency_id"], name="fk_returning_asset_draft_tenant", ondelete="RESTRICT"),
        record_scope("returning_asset"),
        UniqueConstraint("draft_id", "idempotency_key", name="uq_returning_asset_request"),
        CheckConstraint("side IN ('front','back','cover','back_cover','photo')", name="ck_returning_asset_side"),
        CheckConstraint("state IN ('uploading','ready','discarded','adopted','purged')", name="ck_returning_asset_state"),
        CheckConstraint("extraction_status IN ('none','pending','running','succeeded','failed')", name="ck_returning_asset_extraction"),
        CheckConstraint("byte_size > 0 AND byte_size <= 10485760 AND attempts >= 0", name="ck_returning_asset_budget"),
        Index("uq_returning_asset_current", "draft_id", "side", unique=True, postgresql_where=text("is_current"), sqlite_where=text("is_current = 1")),
        Index("ix_returning_asset_cleanup", "state", "created_at", "id"),
        Index("ix_returning_asset_extraction", "extraction_status", "available_at", "id"),
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="uploading")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    fields_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    extraction_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TravellerDraftContactProofModel(DraftRecord, Base):
    __tablename__ = "traveller_draft_contact_proofs"
    __table_args__ = (
        ForeignKeyConstraint(["draft_id", "agency_id", "company_id"], ["traveller_returning_drafts.id", "traveller_returning_drafts.agency_id", "traveller_returning_drafts.company_id"], name="fk_draft_contact_company_owner", ondelete="RESTRICT"),
        ForeignKeyConstraint(["draft_id", "agency_id"], ["traveller_returning_drafts.id", "traveller_returning_drafts.agency_id"], name="fk_draft_contact_owner", ondelete="RESTRICT"),
        UniqueConstraint("draft_id", name="uq_draft_contact_owner"),
        CheckConstraint("status IN ('sending','pending','failed','locked','verified','consumed')", name="ck_draft_contact_status"),
        CheckConstraint("attempt_count >= 0 AND max_attempts > 0", name="ck_draft_contact_attempts"),
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    phone_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    phone_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resend_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    proof_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
