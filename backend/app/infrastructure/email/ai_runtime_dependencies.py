"""Typed call-time runtime services preserve worker and test boundaries."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.email_ai_analysis import EmailAnalysisResult
from app.infrastructure.database.email_ai_models import (
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.infrastructure.email.ai_claim import EmailAiClaim
from app.infrastructure.repositories.notification_repository import NotificationRepository


class ClaimLoader(Protocol):
    async def __call__(
        self, session: AsyncSession, claim: EmailAiClaim, *, for_update: bool
    ) -> tuple[EmailAiAnalysisModel, EmailMessageModel, EmailConnectionModel] | None: ...


class PolicyAllows(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        agency_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        connection_id: uuid.UUID,
        lock_namespace: bool = False,
    ) -> bool: ...


class AttentionNotification(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        analysis: EmailAiAnalysisModel,
        message: EmailMessageModel,
        connection: EmailConnectionModel,
        result: EmailAnalysisResult,
        deadlines: list[EmailDetectedDeadlineModel],
        draft: EmailReplyDraftModel | None,
        proposal_count: int,
        notification_window_days: int,
        linked_group_name: str | None = None,
    ) -> None: ...


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True)
class ClaimDependencies:
    session_factory: SessionFactory
    load_valid_claim: ClaimLoader
    notification_repository: Callable[[AsyncSession], NotificationRepository]


@dataclass(frozen=True)
class PersistenceDependencies:
    session_factory: SessionFactory
    load_valid_claim: ClaimLoader
    policy_allows: PolicyAllows
    create_attention_notification: AttentionNotification
