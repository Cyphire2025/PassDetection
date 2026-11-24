"""Owner-scoped provenance between email artifacts and distributed documents."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.email_models import _utcnow
from app.infrastructure.database.model_base import JSONB, Base


class EmailArtifactDocumentModel(Base):
    """Traceability link from an email artifact to the reused document pipeline."""
    __module__ = "app.infrastructure.database.email_models"

    __tablename__ = "email_artifact_documents"
    __table_args__ = (
        UniqueConstraint(
            "artifact_id",
            "distributed_document_id",
            name="uq_email_artifact_documents_artifact_document",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "agency_id"],
            ["email_artifacts.id", "email_artifacts.agency_id"],
            name="fk_email_artifact_documents_artifact_agency",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["artifact_id", "agency_id", "owner_user_id"],
            [
                "email_artifacts.id",
                "email_artifacts.agency_id",
                "email_artifacts.owner_user_id",
            ],
            name="fk_email_artifact_documents_artifact_agency_owner",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "result_type IN ("
            "'created', 'existing_duplicate', 'revision_candidate', 'conflict_candidate'"
            ")",
            name="ck_email_artifact_documents_result_type",
        ),
        CheckConstraint(
            "match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)",
            name="ck_email_artifact_documents_confidence",
        ),
        Index(
            "ix_email_artifact_documents_agency_document",
            "agency_id",
            "distributed_document_id",
        ),
        Index(
            "ix_email_artifact_documents_owner_document",
            "owner_user_id",
            "distributed_document_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    artifact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    distributed_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("distributed_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    result_type: Mapped[str] = mapped_column(String(32), nullable=False)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    match_evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        server_default=text("CURRENT_TIMESTAMP"),
    )
