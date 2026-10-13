"""Durable proof state: public identifiers are never the stored bearer secrets.

Every answer attempt and transition is serialized by a claim/person row lock.
Challenge selection survives claim restarts, and the person attempt budget is
shared across routes and phones. Expiry and authority are rechecked by services.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import JSONB, Base
from app.infrastructure.database.traveller_model_support import (
    TravellerRecord,
    company_scope,
    document_scope,
    group_scope,
    passport_scope,
    record_scope,
    traveller_scope,
)


class TravellerClaimModel(TravellerRecord, Base):
    __tablename__ = "traveller_claims"
    __table_args__ = (
        company_scope("traveller_claim"),
        group_scope("traveller_claim"),
        traveller_scope("traveller_claim"),
        passport_scope("traveller_claim"),
        document_scope("traveller_claim"),
        record_scope("traveller_claim"),
        UniqueConstraint("secret_hash", name="uq_traveller_claim_secret"),
        UniqueConstraint("id", "agency_id", "company_id", "group_id", "traveller_id", "passport_id", "document_revision_id", name="uq_traveller_claim_grant_binding"),
        UniqueConstraint(
            "agency_id", "company_id", "group_id", "idempotency_key", name="uq_traveller_claim_idempotency"
        ),
        CheckConstraint("method IN ('phone','passport','code')", name="ck_traveller_claim_method"),
        CheckConstraint(
            "status IN ('created','otp_sending','otp_pending','otp_verified','passport_matched',"
            "'challenge_passed','recovery_confirmation','authorized','consumed','revoked','locked')",
            name="ck_traveller_claim_status",
        ),
        CheckConstraint(
            "actor_kind IN ('self','delegate','guardian')", name="ck_traveller_claim_actor"
        ),
        CheckConstraint(
            "failed_answer_sets BETWEEN 0 AND 5 AND required_question_count BETWEEN 0 AND 2",
            name="ck_traveller_claim_answers",
        ),
        CheckConstraint(
            "otp_attempt_count >= 0 AND max_attempts >= 1", name="ck_traveller_claim_otp_attempts"
        ),
        CheckConstraint(
            "passport_id IS NULL OR traveller_id IS NOT NULL",
            name="ck_traveller_claim_passport_owner",
        ),
        CheckConstraint(
            "document_revision_id IS NULL OR passport_id IS NOT NULL",
            name="ck_traveller_claim_document_owner",
        ),
        CheckConstraint("expires_at > created_at", name="ck_traveller_claim_expiry"),
        Index("ix_traveller_claim_person", "agency_id", "company_id", "traveller_id", "status"),
        Index("ix_traveller_claim_expiry", "expires_at", "id"),
        Index("ix_traveller_claim_group", "agency_id", "company_id", "group_id", "status"),
    )
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="created", server_default="created"
    )
    phone_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    otp_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    otp_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    otp_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_resend_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    traveller_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    passport_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    document_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    expected_profile_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_contact_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_authorization_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_company_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_group_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_policy_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplied_passport_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    identifier_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    required_question_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    failed_answer_sets: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    actor_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="self", server_default="self"
    )
    actor_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)


class TravellerChallengeSelectionModel(TravellerRecord, Base):
    __tablename__ = "traveller_challenge_selections"
    __table_args__ = (
        document_scope("traveller_challenge_selection"),
        record_scope("traveller_challenge_selection"),
        UniqueConstraint(
            "traveller_id",
            "document_revision_id",
            "purpose",
            name="uq_traveller_challenge_selection",
        ),
        Index("ix_traveller_challenge_expiry", "expires_at", "id"),
        CheckConstraint("expires_at > created_at", name="ck_traveller_challenge_expiry"),
    )
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passport_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(64), nullable=False, default="history_reuse", server_default="history_reuse"
    )
    fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TravellerAttemptBudgetModel(Base):
    __tablename__ = "traveller_attempt_budgets"
    __table_args__ = (
        traveller_scope("traveller_attempt_budget"),
        CheckConstraint(
            "failure_count BETWEEN 0 AND 5 AND revision >= 1",
            name="ck_traveller_attempt_budget_values",
        ),
        Index("ix_traveller_attempt_budget_cooldown", "cooldown_until", "traveller_id"),
    )
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class TravellerCandidateHandleModel(TravellerRecord, Base):
    __tablename__ = "traveller_candidate_handles"
    __table_args__ = (
        traveller_scope("traveller_candidate_handle"),
        ForeignKeyConstraint(
            ["claim_id", "agency_id", "company_id"],
            ["traveller_claims.id", "traveller_claims.agency_id", "traveller_claims.company_id"],
            name="fk_traveller_candidate_claim_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("token_hash", name="uq_traveller_candidate_handle_token"),
        UniqueConstraint("claim_id", "traveller_id", name="uq_traveller_candidate_claim_person"),
        Index("ix_traveller_candidate_expiry", "expires_at", "id"),
    )
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TravellerHistoryGrantModel(TravellerRecord, Base):
    __tablename__ = "traveller_history_grants"
    __table_args__ = (
        group_scope("traveller_history_grant"),
        document_scope("traveller_history_grant"),
        record_scope("traveller_history_grant"),
        ForeignKeyConstraint(
            ["claim_id", "agency_id", "company_id", "group_id", "traveller_id", "passport_id", "document_revision_id"],
            ["traveller_claims.id", "traveller_claims.agency_id", "traveller_claims.company_id", "traveller_claims.group_id", "traveller_claims.traveller_id", "traveller_claims.passport_id", "traveller_claims.document_revision_id"],
            name="fk_traveller_history_grant_claim_scope",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("secret_hash", name="uq_traveller_history_grant_secret"),
        UniqueConstraint("claim_id", name="uq_traveller_history_grant_claim"),
        CheckConstraint(
            "actor_kind IN ('self','delegate','guardian')", name="ck_traveller_grant_actor"
        ),
        CheckConstraint(
            "profile_revision >= 1 AND contact_revision >= 1 AND authorization_version >= 1 AND policy_revision >= 1 AND company_revision >= 1 AND group_revision >= 1",
            name="ck_traveller_grant_revisions",
        ),
        CheckConstraint(
            "inactivity_expires_at <= absolute_expires_at AND last_used_at >= created_at AND absolute_expires_at > created_at",
            name="ck_traveller_grant_lifetime",
        ),
        Index("ix_traveller_grant_person", "agency_id", "company_id", "traveller_id", "revoked_at"),
        Index("ix_traveller_grant_group", "agency_id", "company_id", "group_id", "revoked_at"),
        Index("ix_traveller_grant_expiry", "absolute_expires_at", "id"),
    )
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    passport_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_revision_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    contact_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    authorization_version: Mapped[int] = mapped_column(Integer, nullable=False)
    company_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    group_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    allowed_actions: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inactivity_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
