"""Retained MCP origin barriers for the existing native authored-push worker.

No authority lock is requested while a pre-claim parent lock is held. The native
sender commits claims, then obtains original authority -> plan -> parent locks.
One wave contains ordinary notifications OR one MCP plan. Keeping the classes
separate prevents a parent->registration ordinary writer from cycling against
the MCP registration->parent authority barrier.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.gc_push_snapshots import device_snapshot, digest
from app.core.config.settings import get_settings
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobileNotificationModel,
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)
from app.infrastructure.database.gc_notification_models import GCNotificationRecipientModel
from app.infrastructure.database.mcp_gc_push_models import MCPGCPushOriginModel, MCPGCPushPlanModel
from app.infrastructure.database.models import AgencyModel, ClientGroupModel

BLOCKED = "mcp_origin_unavailable"


async def observe_push(session: AsyncSession, notifications: list[MobileNotificationModel]) -> None:
    ids = [item.id for item in notifications if item.notification_type == "gc_alert"]
    if ids:
        from app.application.mcp.gc_push_progress import refresh_notification_progress

        await session.flush()
        await refresh_notification_progress(session, ids)


async def origins(
    session: AsyncSession, notifications: list[MobileNotificationModel]
) -> dict[uuid.UUID, MCPGCPushOriginModel]:
    ids = [item.id for item in notifications if item.notification_type == "gc_alert"]
    if not ids:
        return {}
    return {
        row.notification_id: row
        for row in await session.scalars(
            select(MCPGCPushOriginModel).where(MCPGCPushOriginModel.notification_id.in_(ids))
        )
    }


async def one_origin_wave(
    session: AsyncSession,
    notifications: list[MobileNotificationModel],
    *,
    now: datetime,
    provider: str,
) -> list[MobileNotificationModel]:
    bindings = await origins(session, notifications)
    first = bindings.get(notifications[0].id) if notifications else None
    selected = first.plan_id if first is not None else None
    result = []
    for item in notifications:
        binding = bindings.get(item.id)
        if binding is None:
            if first is None:
                result.append(item)
        elif first is not None and binding.plan_id == selected:
            plan = (
                await session.get(MCPGCPushPlanModel, binding.plan_id) if binding.plan_id else None
            )
            if (
                provider not in {"fcm", "apns"}
                or plan is None
                or plan.status != "queued"
                or plan.draft_id is None
            ):
                await block_unsent(session, item, now=now)
            else:
                result.append(item)
    return result


async def block_unsent(
    session: AsyncSession, notification: MobileNotificationModel, *, now: datetime
) -> None:
    """Preserve accepted/uncertain history; only definitely-unsent retry rows fail."""
    rows = list(
        await session.scalars(
            select(MobilePushDeliveryModel).where(
                MobilePushDeliveryModel.notification_id == notification.id
            )
        )
    )
    for row in rows:
        if row.status == "retry":
            row.status, row.last_error_code, row.updated_at = "failed", BLOCKED, now
            row.failed_at = now
    if not any(
        row.status in {"provider_accepted", "delivered", "receipt_pending", "unknown", "submitting"}
        for row in rows
    ):
        notification.status, notification.failure_code, notification.updated_at = (
            "failed",
            BLOCKED,
            now,
        )


async def frozen_registrations(
    session: AsyncSession,
    notifications: list[MobileNotificationModel],
    registrations: dict[Any, list[Any]],
) -> dict[Any, list[Any]]:
    """Current website authority is necessary; saved targets additionally bound MCP sends."""
    bindings = await origins(session, notifications)
    if not bindings:
        return registrations
    from app.application.mobile.authored_notification_access import (
        authored_notification_recipient_key,
    )

    result = dict(registrations)
    for notification in notifications:
        binding = bindings.get(notification.id)
        if binding is None:
            continue
        key = authored_notification_recipient_key(notification)
        plan = await session.get(MCPGCPushPlanModel, binding.plan_id) if binding.plan_id else None
        recipient = await session.get(
            GCNotificationRecipientModel, notification.authored_recipient_id
        )
        expected = (
            {
                device["registration_id"]: device
                for device in plan.snapshot["devices"]
                if recipient is not None and device["person_key"] == recipient.person_key
            }
            if plan
            else {}
        )
        if (
            plan is None
            or binding.batch_id != plan.batch_id
            or recipient is None
            or recipient.batch_id != plan.batch_id
            or notification.agency_id != plan.agency_id
            or notification.title != plan.snapshot["title"]
            or notification.body != plan.snapshot["body"]
            or notification.lock_screen_title != notification.title
            or notification.lock_screen_body != notification.body
        ):
            expected = {}
        result[key] = (
            [
                row
                for row in registrations.get(key, [])
                if (
                    expected.get(str(row.id))
                    == device_snapshot(row) | {"person_key": recipient.person_key}
                )
            ]
            if recipient is not None
            else []
        )
    return result


async def lock_original_authority(
    session: AsyncSession, notifications: list[MobileNotificationModel]
) -> set[uuid.UUID]:
    """Called after durable claim COMMIT, before any parent/target locks or HTTP."""
    bindings = await origins(session, notifications)
    if not bindings:
        return set()
    denied = set(bindings)
    plan_ids = {row.plan_id for row in bindings.values()}
    if len(plan_ids) != 1 or None in plan_ids:
        return denied
    plan_id = next(iter(plan_ids))
    identity = (
        await session.execute(
            select(MCPGCPushPlanModel.original_grant_id, MCPGCPushPlanModel.user_id).where(
                MCPGCPushPlanModel.id == plan_id
            )
        )
    ).first()
    if identity is None or identity.original_grant_id is None or identity.user_id is None:
        return denied
    settings = get_settings()
    auth = MCPAuthorizationService(session, settings)
    try:
        grant = await auth.require_grant(identity.original_grant_id, lock=True)
        auth.require_capability(grant, "mcp:communicate")
    except MCPAuthError:
        return denied
    plan = await session.scalar(
        select(MCPGCPushPlanModel)
        .where(MCPGCPushPlanModel.id == plan_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        plan is None
        or plan.status != "queued"
        or plan.draft_id is None
        or plan.user_id != grant.user_id
        or plan.original_grant_id != grant.id
        or digest(plan.snapshot) != plan.snapshot_hash
    ):
        return denied
    agency = await session.scalar(
        select(AgencyModel)
        .where(AgencyModel.id == plan.agency_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if agency is None or not agency.is_active:
        return denied
    group_ids = [uuid.UUID(item[0]) for item in plan.snapshot["groups"]]
    await session.execute(
        select(ClientGroupModel.id)
        .where(ClientGroupModel.id.in_(group_ids))
        .order_by(ClientGroupModel.id)
        .with_for_update(read=True)
    )
    await session.execute(
        select(GCGroupAccessModel.id)
        .where(GCGroupAccessModel.group_id.in_(group_ids))
        .order_by(GCGroupAccessModel.id)
        .with_for_update(read=True)
    )
    await session.execute(
        select(MobileDeviceSessionModel.id)
        .where(
            MobileDeviceSessionModel.id.in_(
                {uuid.UUID(item["session_id"]) for item in plan.snapshot["devices"]}
            )
        )
        .order_by(MobileDeviceSessionModel.id)
        .with_for_update(read=True)
    )
    await session.execute(
        select(MobilePushRegistrationModel.id)
        .where(
            MobilePushRegistrationModel.id.in_(
                {uuid.UUID(item["registration_id"]) for item in plan.snapshot["devices"]}
            )
        )
        .order_by(MobilePushRegistrationModel.id)
        .with_for_update()
    )
    for item in notifications:
        binding = bindings.get(item.id)
        if binding is None:
            continue
        recipient = await session.get(GCNotificationRecipientModel, item.authored_recipient_id)
        if (
            binding.batch_id == plan.batch_id
            and item.agency_id == plan.agency_id
            and recipient is not None
            and recipient.batch_id == plan.batch_id
            and item.title == plan.snapshot["title"]
            and item.body == plan.snapshot["body"]
            and item.lock_screen_title == item.title
            and item.lock_screen_body == item.body
        ):
            denied.discard(item.id)
    return denied


async def recheck_handoff_clock(
    session: AsyncSession, notifications: list[MobileNotificationModel]
) -> set[uuid.UUID]:
    """Read-only final clock check after waiting for source/parent locks.

    The authority lock was acquired before those locks. Reusing it must not
    let an elapsed grant/MFA deadline authorize a later provider handoff.
    """
    bindings = await origins(session, notifications)
    denied: set[uuid.UUID] = set()
    auth = MCPAuthorizationService(session, get_settings())
    for plan_id in {row.plan_id for row in bindings.values()}:
        plan = await session.get(MCPGCPushPlanModel, plan_id) if plan_id else None
        valid = False
        if plan is not None and plan.original_grant_id is not None:
            try:
                grant = await auth.require_grant(plan.original_grant_id)
                auth.require_capability(grant, "mcp:communicate")
                valid = grant.user_id == plan.user_id
            except MCPAuthError:
                pass
        if not valid:
            denied.update(
                identifier for identifier, row in bindings.items() if row.plan_id == plan_id
            )
    return denied
