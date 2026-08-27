"""Bounded retention cleanup for temporary workforce identity records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.core.config.settings import Settings, get_settings
from app.infrastructure.database.models import (
    DashboardAuthChallengeModel,
    IdentityActionTokenModel,
    IdentityNotificationOutboxModel,
    MFARecoveryCodeModel,
    UserModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.observability.metrics import metrics


@dataclass(frozen=True, slots=True)
class IdentityRetentionResult:
    action_tokens: int
    auth_challenges: int
    recovery_codes: int
    notification_outbox: int

    @property
    def total(self) -> int:
        return (
            self.action_tokens
            + self.auth_challenges
            + self.recovery_codes
            + self.notification_outbox
        )


async def _bounded_ids(
    session: AsyncSession,
    id_column: InstrumentedAttribute[uuid.UUID],
    *criteria: ColumnElement[bool],
    limit: int,
) -> list[uuid.UUID]:
    statement = (
        select(id_column)
        .where(*criteria)
        .order_by(id_column)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list((await session.execute(statement)).scalars().all())


async def apply_identity_retention(
    *,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
    settings: Settings | None = None,
    agency_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> IdentityRetentionResult:
    """Delete only terminal/expired rows in one restart-safe bounded page."""

    active = settings or get_settings()
    active_now = now or datetime.now(tz=UTC)
    general_cutoff = active_now - timedelta(days=active.identity_token_retention_days)
    consumed_cutoff = active_now - timedelta(days=active.identity_consumed_token_retention_days)
    challenge_cutoff = active_now - timedelta(days=active.identity_challenge_retention_days)
    limit = active.identity_retention_batch_size

    async with session_factory() as session:
        async with session.begin():
            action_scope: list[ColumnElement[bool]] = []
            if agency_id is not None:
                action_scope.append(
                    IdentityActionTokenModel.user_id.in_(
                        select(UserModel.id).where(UserModel.agency_id == agency_id)
                    )
                )
            action_ids = await _bounded_ids(
                session,
                IdentityActionTokenModel.id,
                *action_scope,
                or_(
                    IdentityActionTokenModel.consumed_at <= consumed_cutoff,
                    IdentityActionTokenModel.invalidated_at <= general_cutoff,
                    IdentityActionTokenModel.expires_at <= general_cutoff,
                ),
                limit=limit,
            )
            if action_ids:
                await session.execute(
                    delete(IdentityActionTokenModel).where(
                        IdentityActionTokenModel.id.in_(action_ids)
                    )
                )

            challenge_scope: list[ColumnElement[bool]] = []
            if agency_id is not None:
                challenge_scope.append(
                    DashboardAuthChallengeModel.user_id.in_(
                        select(UserModel.id).where(UserModel.agency_id == agency_id)
                    )
                )
            challenge_ids = await _bounded_ids(
                session,
                DashboardAuthChallengeModel.id,
                *challenge_scope,
                DashboardAuthChallengeModel.created_at <= challenge_cutoff,
                or_(
                    DashboardAuthChallengeModel.status.in_(
                        ("consumed", "expired", "locked", "cancelled")
                    ),
                    DashboardAuthChallengeModel.expires_at <= challenge_cutoff,
                ),
                limit=limit,
            )
            if challenge_ids:
                await session.execute(
                    delete(DashboardAuthChallengeModel).where(
                        DashboardAuthChallengeModel.id.in_(challenge_ids)
                    )
                )

            code_scope: list[ColumnElement[bool]] = []
            if agency_id is not None:
                code_scope.append(
                    MFARecoveryCodeModel.user_id.in_(
                        select(UserModel.id).where(UserModel.agency_id == agency_id)
                    )
                )
            code_ids = await _bounded_ids(
                session,
                MFARecoveryCodeModel.id,
                *code_scope,
                MFARecoveryCodeModel.consumed_at <= consumed_cutoff,
                limit=limit,
            )
            if code_ids:
                await session.execute(
                    delete(MFARecoveryCodeModel).where(MFARecoveryCodeModel.id.in_(code_ids))
                )

            outbox_scope: list[ColumnElement[bool]] = []
            if agency_id is not None:
                outbox_scope.append(IdentityNotificationOutboxModel.agency_id == agency_id)
            outbox_ids = await _bounded_ids(
                session,
                IdentityNotificationOutboxModel.id,
                *outbox_scope,
                or_(
                    (
                        IdentityNotificationOutboxModel.status.in_(("delivered", "dead_letter"))
                        & (IdentityNotificationOutboxModel.updated_at <= general_cutoff)
                    ),
                    (
                        IdentityNotificationOutboxModel.action_token_id.is_(None)
                        & (IdentityNotificationOutboxModel.created_at <= general_cutoff)
                    ),
                ),
                limit=limit,
            )
            if outbox_ids:
                await session.execute(
                    delete(IdentityNotificationOutboxModel).where(
                        IdentityNotificationOutboxModel.id.in_(outbox_ids)
                    )
                )

    result = IdentityRetentionResult(
        action_tokens=len(action_ids),
        auth_challenges=len(challenge_ids),
        recovery_codes=len(code_ids),
        notification_outbox=len(outbox_ids),
    )
    metrics.increment("identity.retention.runs")
    metrics.increment("identity.retention.rows_deleted", result.total)
    metrics.increment("identity.retention.action_tokens_deleted", result.action_tokens)
    metrics.increment("identity.retention.auth_challenges_deleted", result.auth_challenges)
    metrics.increment("identity.retention.recovery_codes_deleted", result.recovery_codes)
    metrics.increment("identity.retention.notification_outbox_deleted", result.notification_outbox)
    return result


__all__ = ["IdentityRetentionResult", "apply_identity_retention"]
