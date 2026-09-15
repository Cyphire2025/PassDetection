"""Read-only production notification evidence, without tokens or traveller data.

Run inside the deployed backend container. Optional UUID filters narrow the
announcement list; registration inventory is explicitly server-wide. This never
publishes, dispatches, re-registers a device or changes an account's access.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def queued_notification_inventory(session: AsyncSession) -> list[dict[str, Any]]:
    """Count all queue types before source/access/device eligibility checks."""
    from sqlalchemy import and_, func, or_, select

    from app.infrastructure.database.gc_mobile_models import MobileNotificationModel as Notification

    now = datetime.now(UTC)
    unexpired = or_(Notification.expires_at.is_(None), Notification.expires_at > now)
    rows = (await session.execute(
        select(
            Notification.notification_type,
            func.count(),
            func.count().filter(and_(Notification.available_at <= now, unexpired)),
            func.count().filter(Notification.available_at > now),
            func.count().filter(Notification.expires_at <= now),
            func.count().filter(Notification.read_at.is_not(None)),
            func.min(Notification.available_at),
        )
        .where(Notification.status == "queued")
        .group_by(Notification.notification_type)
        .order_by(Notification.notification_type)
    )).all()
    return [
        {"notification_type": kind, "queued": count, "due_now": due,
         "scheduled_for_later": future, "expired": expired,
         "already_read_in_app": read, "oldest_available_at": oldest}
        for kind, count, due, future, expired, read, oldest in rows
    ]


async def collect_evidence(
    session: AsyncSession,
    *,
    group_id: UUID | None = None,
    announcement_id: UUID | None = None,
) -> dict[str, Any]:
    from sqlalchemy import func, select, text

    from app.application.mobile.announcement_notification_status import (
        announcement_notification_status,
    )
    from app.core.config.settings import get_settings
    from app.infrastructure.database.gc_mobile_models import (
        GCAnnouncementModel,
        MobilePushRegistrationModel,
    )

    # Server-side protection as well as SELECT-only application code.
    await session.execute(text("SET TRANSACTION READ ONLY"))
    await session.execute(text("SET LOCAL statement_timeout = '15s'"))
    settings = get_settings()
    enabled = settings.mobile.enabled and settings.mobile.push_provider != "disabled"
    schema = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalars().all()
    registrations = (await session.execute(
        select(
            MobilePushRegistrationModel.provider,
            MobilePushRegistrationModel.platform,
            MobilePushRegistrationModel.environment,
            MobilePushRegistrationModel.status,
            func.count(MobilePushRegistrationModel.id),
        ).group_by(
            MobilePushRegistrationModel.provider,
            MobilePushRegistrationModel.platform,
            MobilePushRegistrationModel.environment,
            MobilePushRegistrationModel.status,
        )
    )).all()
    query = select(GCAnnouncementModel).order_by(GCAnnouncementModel.created_at.desc()).limit(10)
    if group_id is not None:
        query = query.where(GCAnnouncementModel.group_id == group_id)
    if announcement_id is not None:
        query = query.where(GCAnnouncementModel.id == announcement_id)
    announcements = (await session.scalars(query)).all()
    summaries = []
    for announcement in announcements:
        status = await announcement_notification_status(
            session,
            agency_id=announcement.agency_id,
            group_id=announcement.group_id,
            access_id=announcement.gc_group_access_id,
            announcement_id=announcement.id,
            provider_enabled=enabled,
        )
        summaries.append({
            **asdict(status),
            "group_id": announcement.group_id,
            "content_status": announcement.status,
            "priority": announcement.priority,
            "version": announcement.version,
        })
    return {
        "checked_at": datetime.now(UTC),
        "app_revision": os.getenv("APP_REVISION", "unavailable"),
        "database_schema": list(schema),
        "configuration": {
            "mobile_enabled": settings.mobile.enabled,
            "push_provider": settings.mobile.push_provider,
            "push_access_token_present": bool(settings.mobile.push_access_token),
            "dispatch_interval_seconds": settings.mobile.push_dispatch_interval_seconds,
            "receipt_poll_interval_seconds": settings.mobile.push_receipt_poll_interval_seconds,
            "initial_receipt_delay_seconds": settings.mobile.push_receipt_initial_delay_seconds,
        },
        "registration_inventory_scope": "server-wide; active rows do not prove this recipient has an authorized device",
        "registration_inventory": [
            {"provider": provider, "platform": platform, "environment": environment,
             "status": state, "count": count}
            for provider, platform, environment, state, count in registrations
        ],
        "queued_notification_inventory_scope": (
            "server-wide, before source/access/device checks; due_now is not a delivery prediction"
        ),
        "queued_notification_inventory": await queued_notification_inventory(session),
        "announcements": summaries,
        "evidence_limit": "Configuration and database evidence only. Worker execution and visible phone banners must be checked separately.",
    }


async def diagnose(args: argparse.Namespace) -> None:
    from app.infrastructure.database.session import AsyncSessionFactory, engine

    try:
        async with AsyncSessionFactory() as session:
            result = await collect_evidence(
                session, group_id=args.group_id, announcement_id=args.announcement_id,
            )
            await session.rollback()
        print(json.dumps(result, default=str, indent=2))
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group-id", type=UUID)
    parser.add_argument("--announcement-id", type=UUID)
    args = parser.parse_args()
    try:
        asyncio.run(diagnose(args))
    except Exception as error:
        # Driver exceptions may include connection strings. Keep output bounded.
        print(f"Diagnostic failed ({type(error).__name__}); no changes were made.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
