"""Due-mailbox claims and immutable owner/generation envelopes for dispatch."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update

from app.core.config.settings import get_settings
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.session import AsyncSessionFactory


@dataclass(frozen=True)
class EmailSyncTaskEnvelope:
    connection_id: uuid.UUID
    agency_id: uuid.UUID
    owner_user_id: uuid.UUID
    provider_account_id: str
    sync_generation: int

    def task_kwargs(self) -> dict[str, str | int]:
        return {
            "connection_id": str(self.connection_id),
            "agency_id": str(self.agency_id),
            "owner_user_id": str(self.owner_user_id),
            "provider_account_id": self.provider_account_id,
            "sync_generation": self.sync_generation,
        }


async def _claim_due_dispatches() -> list[EmailSyncTaskEnvelope]:
    settings = get_settings()
    now = datetime.now(tz=UTC)
    async with AsyncSessionFactory() as session:
        # When an operator lowers the polling interval, do not leave healthy
        # idle connections waiting on their previously longer schedule.
        await session.execute(
            update(EmailConnectionModel)
            .where(
                EmailConnectionModel.status == "active",
                EmailConnectionModel.owner_user_id.is_not(None),
                EmailConnectionModel.sync_state == "idle",
                EmailConnectionModel.next_sync_at.is_not(None),
                EmailConnectionModel.next_sync_at
                > now + timedelta(seconds=settings.email_sync_interval_seconds),
                or_(
                    EmailConnectionModel.sync_lease_expires_at.is_(None),
                    EmailConnectionModel.sync_lease_expires_at <= now,
                ),
            )
            .values(next_sync_at=now)
            .execution_options(synchronize_session=False)
        )
        result = await session.execute(
            select(EmailConnectionModel)
            .where(
                EmailConnectionModel.status.in_({"active", "failing"}),
                EmailConnectionModel.owner_user_id.is_not(None),
                EmailConnectionModel.next_sync_at.is_not(None),
                EmailConnectionModel.next_sync_at <= now,
                or_(
                    EmailConnectionModel.sync_lease_expires_at.is_(None),
                    EmailConnectionModel.sync_lease_expires_at <= now,
                ),
            )
            .order_by(EmailConnectionModel.next_sync_at.asc())
            .limit(100)
            .with_for_update(skip_locked=True)
        )
        connections = list(result.scalars().all())
        for connection in connections:
            connection.sync_state = "queued"
            connection.next_sync_at = now + timedelta(seconds=settings.email_sync_interval_seconds)
        await session.commit()
        return [
            EmailSyncTaskEnvelope(
                connection_id=connection.id,
                agency_id=connection.agency_id,
                owner_user_id=connection.owner_user_id,
                provider_account_id=connection.provider_account_id,
                sync_generation=connection.sync_generation,
            )
            for connection in connections
        ]


# Keep existing imports, pickle names, and evaluated annotations compatible.
EmailSyncTaskEnvelope.__module__ = "app.infrastructure.email.tasks"
EmailSyncTaskEnvelope.task_kwargs.__module__ = "app.infrastructure.email.tasks"
_claim_due_dispatches.__module__ = "app.infrastructure.email.tasks"
