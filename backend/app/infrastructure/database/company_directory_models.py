"""Rebuildable company directory indexes; names remain encrypted at rest."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.model_base import Base, _utcnow
from app.infrastructure.database.traveller_model_support import (
    company_scope,
    group_scope,
    traveller_scope,
)


class CompanyDirectoryScope:
    agency_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class CompanyDirectoryStateModel(CompanyDirectoryScope, Base):
    __tablename__ = "company_directory_states"
    __table_args__ = (company_scope("company_directory_state"), Index("ix_company_directory_backfill", "backfill_complete", "company_id"))
    company_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, server_default="1")
    backfill_after: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    backfill_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")


class CompanyDirectoryPersonModel(CompanyDirectoryScope, Base):
    __tablename__ = "company_directory_people"
    __table_args__ = (traveller_scope("company_directory_person"),
        CheckConstraint("submission_count >= 0 AND profile_revision >= 1", name="ck_company_directory_counts"),
        CheckConstraint("length(name_rank) = 78", name="ck_company_directory_rank"),
        Index("ix_company_directory_name", "agency_id", "company_id", "name_rank", "traveller_id", unique=True),
        Index("ix_company_directory_latest", "agency_id", "company_id", "latest_sort_at", "traveller_id"),
        Index("ix_company_directory_count_name", "agency_id", "company_id", "submission_count", "name_rank", "traveller_id"))
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    name_rank: Mapped[str] = mapped_column(String(78), nullable=False)
    profile_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    key_version: Mapped[str] = mapped_column(String(32), nullable=False)
    submission_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    latest_submission_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latest_sort_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)


class CompanyDirectoryPrefixModel(CompanyDirectoryScope, Base):
    __tablename__ = "company_directory_prefixes"
    __table_args__ = (traveller_scope("company_directory_prefix"),
        Index("ix_company_directory_prefix_seek", "agency_id", "company_id", "key_version", "token_digest", "traveller_id"))
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    token_digest: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    key_version: Mapped[str] = mapped_column(String(32), nullable=False)


class CompanyDirectoryGroupCountModel(CompanyDirectoryScope, Base):
    __tablename__ = "company_directory_group_counts"
    __table_args__ = (traveller_scope("company_directory_group_count"), group_scope("company_directory_group_count"),
        CheckConstraint("submission_count >= 1", name="ck_company_directory_group_count"),
        Index("ix_company_directory_group_scope", "agency_id", "company_id", "group_id", "traveller_id"))
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    submission_count: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_submission_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CompanyDirectoryQueueModel(CompanyDirectoryScope, Base):
    __tablename__ = "company_directory_queue"
    __table_args__ = (traveller_scope("company_directory_queue"),
        Index("ix_company_directory_queue_ready", "available_at", "traveller_id"),
        Index("ix_company_directory_queue_company", "agency_id", "company_id", "traveller_id"))
    traveller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error_code: Mapped[str | None] = mapped_column(String(32))
