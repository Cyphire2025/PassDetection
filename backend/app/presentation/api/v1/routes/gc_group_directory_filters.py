"""Existing tenant-scoped group directory predicates."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.sql.elements import ColumnElement

from app.application.mobile.group_app_availability import GCAppAvailability, availability_filter
from app.domain.entities.entities import GroupStatus
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.models import ClientGroupModel


def build_gc_group_directory_filters(
    *,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID | None,
    lifecycle_status: str | None,
    q: str | None,
    eligible_only: bool,
    gc_enabled: bool | None,
    configured_only: bool,
    unconfigured_only: bool,
    availability: GCAppAvailability | None,
    now: datetime,
) -> tuple[list[ColumnElement[bool]], ColumnElement[bool]]:
    filters: list[ColumnElement[bool]] = [ClientGroupModel.agency_id == tenant_id]
    if group_id is not None:
        filters.append(ClientGroupModel.id == group_id)
    if lifecycle_status is not None:
        if lifecycle_status not in {item.value for item in GroupStatus}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Invalid group lifecycle status",
            )
        filters.append(ClientGroupModel.status == lifecycle_status)
    if q and (normalized := " ".join(q.split())):
        filters.append(
            or_(
                ClientGroupModel.name.icontains(normalized, autoescape=True),
                ClientGroupModel.destination.icontains(normalized, autoescape=True),
            )
        )
    access_join = (GCGroupAccessModel.group_id == ClientGroupModel.id) & (
        GCGroupAccessModel.agency_id == ClientGroupModel.agency_id
    )
    if eligible_only:
        filters.extend(
            [
                ClientGroupModel.status.in_((GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value)),
                ClientGroupModel.deleted_at.is_(None),
                or_(
                    GCGroupAccessModel.id.is_(None),
                    GCGroupAccessModel.is_enabled.is_(False),
                    GCGroupAccessModel.revoked_at.is_not(None),
                ),
            ]
        )
    elif gc_enabled is True:
        filters.extend(
            [
                GCGroupAccessModel.is_enabled.is_(True),
                GCGroupAccessModel.revoked_at.is_(None),
            ]
        )
    elif gc_enabled is False:
        filters.append(
            or_(
                GCGroupAccessModel.id.is_(None),
                GCGroupAccessModel.is_enabled.is_(False),
                GCGroupAccessModel.revoked_at.is_not(None),
            )
        )
    if configured_only:
        filters.extend(
            [
                GCGroupAccessModel.id.is_not(None),
                GCGroupAccessModel.removed_at.is_(None),
            ]
        )
    if unconfigured_only:
        filters.append(
            or_(
                GCGroupAccessModel.id.is_(None),
                GCGroupAccessModel.removed_at.is_not(None),
            )
        )
    if availability is not None:
        filters.append(availability_filter(availability, now=now))
    return filters, access_join
