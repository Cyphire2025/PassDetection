"""Count and page queries with optional page-wide usage metrics."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TypeAlias

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.gc_mobile_models import (
    ClientOrganizationModel,
    GCGroupAccessModel,
    MobileDeviceSessionModel,
)
from app.infrastructure.database.models import ClientGroupModel

GCGroupDirectoryRow: TypeAlias = tuple[
    ClientGroupModel, GCGroupAccessModel | None, ClientOrganizationModel | None, int, int
]


async def query_gc_group_directory(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    now: datetime,
    filters: list[ColumnElement[bool]],
    access_join: ColumnElement[bool],
    gc_enabled: bool | None,
    group_id: uuid.UUID | None,
    configured_only: bool,
    offset: int,
    limit: int,
) -> tuple[int, list[GCGroupDirectoryRow]]:
    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ClientGroupModel)
                .outerjoin(GCGroupAccessModel, access_join)
                .where(*filters)
            )
        ).scalar_one()
    )
    # Enabled-group pages need usage metrics, but candidate searches do not.
    # Aggregate once for the whole page instead of issuing two count queries
    # per group.  The account count and acknowledged-device count deliberately
    # have different semantics and therefore must not reuse one session count.
    include_metrics = gc_enabled is True or group_id is not None or configured_only
    usage_metrics = None
    if include_metrics:
        usage_metrics = (
            select(
                MobileDeviceSessionModel.selected_gc_group_access_id.label("gc_group_access_id"),
                func.count(func.distinct(MobileDeviceSessionModel.account_id)).label(
                    "active_mobile_users"
                ),
                func.count(func.distinct(MobileDeviceSessionModel.device_identifier_hash))
                .filter(MobileDeviceSessionModel.last_sync_acknowledged_at.is_not(None))
                .label("synced_device_count"),
            )
            .where(
                MobileDeviceSessionModel.agency_id == tenant_id,
                MobileDeviceSessionModel.selected_gc_group_access_id.is_not(None),
                MobileDeviceSessionModel.status == "active",
                MobileDeviceSessionModel.revoked_at.is_(None),
                MobileDeviceSessionModel.expires_at > now,
            )
            .group_by(MobileDeviceSessionModel.selected_gc_group_access_id)
            .subquery()
        )

    rows: list[GCGroupDirectoryRow]
    if usage_metrics is not None:
        statement_with_metrics = (
            select(
                ClientGroupModel,
                GCGroupAccessModel,
                ClientOrganizationModel,
                usage_metrics.c.active_mobile_users,
                usage_metrics.c.synced_device_count,
            )
            .outerjoin(
                GCGroupAccessModel,
                access_join,
            )
            .outerjoin(
                ClientOrganizationModel,
                (ClientOrganizationModel.id == ClientGroupModel.company_id)
                & (ClientOrganizationModel.agency_id == ClientGroupModel.agency_id),
            )
            .where(*filters)
            .order_by(ClientGroupModel.created_at.desc(), ClientGroupModel.id.desc())
            .offset(offset)
            .limit(limit)
        )
        statement_with_metrics = statement_with_metrics.outerjoin(
            usage_metrics,
            usage_metrics.c.gc_group_access_id == GCGroupAccessModel.id,
        )
        metric_rows = (await session.execute(statement_with_metrics)).all()
        rows = [
            (
                group,
                access,
                organization,
                int(active_mobile_users or 0),
                int(synced_device_count or 0),
            )
            for (
                group,
                access,
                organization,
                active_mobile_users,
                synced_device_count,
            ) in metric_rows
        ]
    else:
        statement_without_metrics = (
            select(ClientGroupModel, GCGroupAccessModel, ClientOrganizationModel)
            .outerjoin(
                GCGroupAccessModel,
                access_join,
            )
            .outerjoin(
                ClientOrganizationModel,
                (ClientOrganizationModel.id == ClientGroupModel.company_id)
                & (ClientOrganizationModel.agency_id == ClientGroupModel.agency_id),
            )
            .where(*filters)
            .order_by(ClientGroupModel.created_at.desc(), ClientGroupModel.id.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = [
            (group, access, organization, 0, 0)
            for group, access, organization in (
                await session.execute(statement_without_metrics)
            ).all()
        ]
    return total, rows
