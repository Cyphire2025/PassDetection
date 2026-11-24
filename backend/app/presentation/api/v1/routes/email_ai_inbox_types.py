"""Shared display/view types for the owner-scoped email operations inbox."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel

InboxView = Literal[
    "needs_attention",
    "upcoming_deadlines",
    "drafts_ready",
    "waiting",
    "completed_automatically",
    "all_activity",
]


ProposalAction = Literal["approve", "reject", "dismiss"]


SettingsProvider = Callable[[], Settings]
AttentionUpdater = Callable[[AsyncSession, EmailAiAnalysisModel], Awaitable[None]]
