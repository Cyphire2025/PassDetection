"""Seven website mailbox counts; no content, locators or credentials loaded."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.application.security.email_scope import email_owner_filters
from app.application.use_cases.email_integrations.overview import (
    ACTIVE_CONNECTION_STATUSES,
    ACTIVE_REVIEW_STATUSES,
)
from app.domain.entities.entities import User
from app.infrastructure.database.email_models import (
    EmailArtifactDocumentModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)

SUMMARY_FIELDS = ("connected_accounts", "relevant_emails_today", "documents_retrieved_today",
    "automatically_matched_today", "revisions_detected_today", "pending_review", "retrieval_failures_today")


class EmailSummaryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def summary(self, actor: User, *, today: datetime) -> dict[str, int]:
        # Preserve all existing predicates, including >= midnight with no added
        # upper cutoff and the exact JSON boolean comparison evaluated in SQL.
        queries: tuple[Select[tuple[int]], ...] = (
            select(func.count(EmailConnectionModel.id)).where(
                *email_owner_filters(EmailConnectionModel.owner_user_id, EmailConnectionModel.agency_id, actor),
                EmailConnectionModel.status.in_(ACTIVE_CONNECTION_STATUSES)),
            select(func.count(EmailMessageModel.id)).where(
                *email_owner_filters(EmailMessageModel.owner_user_id, EmailMessageModel.agency_id, actor),
                EmailMessageModel.relevance_status == "relevant", EmailMessageModel.received_at >= today),
            select(func.count(EmailArtifactModel.id)).where(
                *email_owner_filters(EmailArtifactModel.owner_user_id, EmailArtifactModel.agency_id, actor),
                EmailArtifactModel.retrieved_at >= today),
            select(func.count(EmailArtifactDocumentModel.id)).where(
                *email_owner_filters(EmailArtifactDocumentModel.owner_user_id, EmailArtifactDocumentModel.agency_id, actor),
                EmailArtifactDocumentModel.created_at >= today,
                EmailArtifactDocumentModel.match_evidence["human_confirmed"].as_boolean().is_(False)),
            select(func.count(EmailReviewItemModel.id)).where(
                *email_owner_filters(EmailReviewItemModel.owner_user_id, EmailReviewItemModel.agency_id, actor),
                EmailReviewItemModel.review_type == "possible_revision", EmailReviewItemModel.created_at >= today),
            select(func.count(EmailReviewItemModel.id)).where(
                *email_owner_filters(EmailReviewItemModel.owner_user_id, EmailReviewItemModel.agency_id, actor),
                EmailReviewItemModel.status.in_(ACTIVE_REVIEW_STATUSES)),
            select(func.count(EmailArtifactModel.id)).where(
                *email_owner_filters(EmailArtifactModel.owner_user_id, EmailArtifactModel.agency_id, actor),
                EmailArtifactModel.retrieval_status == "failed", EmailArtifactModel.last_error_at >= today),
        )
        return {name: int(await self.session.scalar(query) or 0) for name, query in zip(SUMMARY_FIELDS, queries, strict=True)}
