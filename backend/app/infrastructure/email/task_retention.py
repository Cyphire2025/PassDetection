"""Email content retention and post-commit object cleanup orchestration."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from celery.utils.log import get_task_logger
from sqlalchemy import delete, or_, select, update

from app.core.config.settings import get_settings
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailAiFeedbackModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import (
    EmailArtifactModel,
    EmailMessageModel,
    EmailOAuthStateModel,
)
from app.infrastructure.database.models import NotificationModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.email.storage_reconciliation import _reconcile_orphaned_email_storage
from app.infrastructure.storage.minio_repository import MinioStorageRepository

logger = get_task_logger("app.infrastructure.email.tasks")


async def _apply_email_retention() -> int:
    settings = get_settings()
    now = datetime.now(tz=UTC)
    content_cutoff = now - timedelta(days=settings.email_content_retention_days)
    oauth_cutoff = now - timedelta(days=1)
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(EmailArtifactModel)
            .where(
                EmailArtifactModel.storage_key.is_not(None),
                EmailArtifactModel.storage_key.like("email-integrations/%"),
                EmailArtifactModel.processing_status.in_({"completed", "duplicate", "ignored"}),
                EmailArtifactModel.updated_at < content_cutoff,
            )
            .order_by(EmailArtifactModel.updated_at.asc())
            .limit(500)
            .with_for_update(skip_locked=True)
        )
        artifacts = list(result.scalars().all())
        keys = [
            artifact.storage_key
            for artifact in artifacts
            if artifact.storage_key and artifact.storage_key.startswith("email-integrations/")
        ]
        for artifact in artifacts:
            artifact.storage_key = None

        scrubbed = await session.execute(
            update(EmailMessageModel)
            .where(
                EmailMessageModel.received_at < content_cutoff,
                EmailMessageModel.body_excerpt.is_not(None),
                EmailMessageModel.body_excerpt != "",
            )
            .values(body_excerpt="", updated_at=now)
        )
        ai_analyses_scrubbed = await session.execute(
            update(EmailAiAnalysisModel)
            .where(
                EmailAiAnalysisModel.updated_at < content_cutoff,
                or_(
                    EmailAiAnalysisModel.summary.is_not(None),
                    EmailAiAnalysisModel.result_json != {},
                    EmailAiAnalysisModel.context_manifest != {},
                ),
            )
            .values(
                summary=None,
                result_json={},
                context_manifest={},
                updated_at=now,
            )
        )
        deadlines_scrubbed = await session.execute(
            update(EmailDetectedDeadlineModel)
            .where(
                EmailDetectedDeadlineModel.updated_at < content_cutoff,
                or_(
                    EmailDetectedDeadlineModel.source_phrase != "[retained content removed]",
                    EmailDetectedDeadlineModel.resolution_evidence != {},
                ),
            )
            .values(
                source_phrase="[retained content removed]",
                resolution_evidence={},
                updated_at=now,
            )
        )
        proposals_scrubbed = await session.execute(
            update(EmailActionProposalModel)
            .where(
                EmailActionProposalModel.updated_at < content_cutoff,
                or_(
                    EmailActionProposalModel.explanation != "[retained content removed]",
                    EmailActionProposalModel.payload_json != {},
                    EmailActionProposalModel.decision_note.is_not(None),
                    EmailActionProposalModel.execution_result != {},
                ),
            )
            .values(
                explanation="[retained content removed]",
                payload_json={},
                decision_note=None,
                execution_result={},
                updated_at=now,
            )
        )
        drafts_deleted = await session.execute(
            delete(EmailReplyDraftModel).where(
                EmailReplyDraftModel.updated_at < content_cutoff,
            )
        )
        feedback_scrubbed = await session.execute(
            update(EmailAiFeedbackModel)
            .where(
                EmailAiFeedbackModel.created_at < content_cutoff,
                or_(
                    EmailAiFeedbackModel.original_value != {},
                    EmailAiFeedbackModel.corrected_value != {},
                    EmailAiFeedbackModel.note.is_not(None),
                ),
            )
            .values(
                original_value={},
                corrected_value={},
                note=None,
            )
        )
        ai_notifications_scrubbed = await session.execute(
            update(NotificationModel)
            .where(
                NotificationModel.created_at < content_cutoff,
                or_(
                    NotificationModel.category == "email_operations",
                    NotificationModel.type.like("email_ai_%"),
                ),
                or_(
                    NotificationModel.message != "[retained content removed]",
                    NotificationModel.metadata_json != {},
                ),
            )
            .values(
                message="[retained content removed]",
                metadata_json={},
            )
        )
        await session.execute(
            delete(EmailOAuthStateModel).where(
                EmailOAuthStateModel.created_at < oauth_cutoff,
                or_(
                    EmailOAuthStateModel.consumed_at.is_not(None),
                    EmailOAuthStateModel.expires_at < now,
                ),
            )
        )
        await session.commit()
        scrubbed_count = int(getattr(scrubbed, "rowcount", 0) or 0)
        ai_content_count = sum(
            int(getattr(result, "rowcount", 0) or 0)
            for result in (
                ai_analyses_scrubbed,
                deadlines_scrubbed,
                proposals_scrubbed,
                drafts_deleted,
                feedback_scrubbed,
                ai_notifications_scrubbed,
            )
        )

    # Clear durable references before deleting. If object deletion fails, the
    # reconciler below (and the next daily run) can safely retry without
    # leaving database rows pointing at missing files.
    storage = MinioStorageRepository()
    if keys:
        try:
            await storage.delete_files(keys)
        except Exception as exc:
            logger.error(
                "email_retention_storage_delete_failed",
                extra={"error_type": type(exc).__name__},
            )
    orphaned_count = 0
    try:
        orphaned_count = await _reconcile_orphaned_email_storage(
            storage=storage,
            now=now,
        )
    except Exception as exc:
        logger.error(
            "email_storage_reconciliation_failed",
            extra={"error_type": type(exc).__name__},
        )
    return len(keys) + scrubbed_count + ai_content_count + orphaned_count


_apply_email_retention.__module__ = "app.infrastructure.email.tasks"
