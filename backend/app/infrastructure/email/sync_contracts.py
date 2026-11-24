"""Durable email synchronization: contracts."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.sql.elements import ColumnElement

from app.application.use_cases.email_integrations.matching import GroupForAssociation
from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.email_models import EmailConnectionModel

_SUPPORTED_PDF_TYPES = {"visa", "flight_ticket"}
_ACTIVE_REVIEW_STATUSES = {"open", "deferred"}


@dataclass(frozen=True)
class SyncClaim:
    connection_id: uuid.UUID
    agency_id: uuid.UUID
    owner_user_id: uuid.UUID
    provider: str
    provider_account_id: str
    lease_token: str
    generation: int
    access_token: str
    refresh_token: str | None
    token_expires_at: datetime | None
    sync_cursor: str | None


@dataclass(frozen=True)
class SyncResult:
    connection_id: uuid.UUID
    processed_messages: int
    ignored_messages: int
    cursor_reset: bool


@dataclass(frozen=True)
class ReviewedArtifactIngestionResult:
    document_ids: tuple[uuid.UUID, ...]
    storage_keys: tuple[str, ...]
    duplicate: bool


@dataclass(frozen=True)
class EmailRelevanceContext:
    groups: tuple[GroupForAssociation, ...]
    passengers: tuple[PassportSubmission, ...]


def _connection_claim_filters(claim: SyncClaim) -> tuple[ColumnElement[bool], ...]:
    """Revalidate the complete immutable task envelope on every worker write."""

    return (
        EmailConnectionModel.id == claim.connection_id,
        EmailConnectionModel.agency_id == claim.agency_id,
        EmailConnectionModel.owner_user_id == claim.owner_user_id,
        EmailConnectionModel.provider_account_id == claim.provider_account_id,
        EmailConnectionModel.sync_generation == claim.generation,
    )


def _provider_artifact_id(
    provider_message_id: str,
    index: int,
    attachment_id: str | None,
    filename: str,
) -> str:
    if attachment_id:
        return f"attachment:{attachment_id}"[:768]
    return hashlib.sha256(f"{provider_message_id}|{index}|{filename}".encode("utf-8")).hexdigest()


def _stored_relevance_status(value: str) -> str:
    return {
        "relevant": "relevant",
        "possibly_relevant": "possible",
        "unrelated": "ignored",
    }.get(value, "pending")


def _can_ignore_without_artifact_inspection(
    *,
    relevance_status: str,
    has_attachments: bool,
    has_links: bool,
) -> bool:
    """Only ignore text-only messages that have no retrievable evidence."""

    # Links are not relevance evidence. An unrelated link-only message should
    # never enter the human review queue.
    return relevance_status == "unrelated" and not has_attachments
