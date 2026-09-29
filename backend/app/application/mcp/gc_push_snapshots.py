"""Bounded exact snapshots using the same authored notification audience rules."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import MCPOperationError
from app.application.mobile.authored_notification_access import registrations_for_grants
from app.application.mobile.authored_notification_audience import collect_notification_audience
from app.application.mobile.authored_notification_service import require_draft
from app.application.mobile.notification_errors import NotificationWorkflowError
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
    MobilePushRegistrationModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)

MAX_GROUPS, MAX_PEOPLE, MAX_DEVICES = 10, 100, 300


class GCPushDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agency_id: uuid.UUID
    draft_id: uuid.UUID
    expected_revision: int = Field(ge=1)


def digest(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def device_snapshot(row: MobilePushRegistrationModel) -> dict[str, Any]:
    return {
        "registration_id": str(row.id),
        "provider": row.provider,
        "session_id": str(row.session_id),
        "token_lookup_hash": row.token_lookup_hash,
        "apns_environment": row.apns_environment,
    }


def public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    # Exact opaque principal/device IDs are reviewable without disclosing token material.
    return {key: value for key, value in snapshot.items() if key not in {"grants", "devices"}} | {
        "devices": [
            {key: value for key, value in device.items() if key != "token_lookup_hash"}
            for device in snapshot["devices"]
        ]
    }


async def active_agency(session: AsyncSession, agency_id: uuid.UUID) -> None:
    agency = await session.scalar(
        select(AgencyModel)
        .where(AgencyModel.id == agency_id)
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    if agency is None or not agency.is_active:
        raise MCPAuthError("access_denied", 403)


async def _recipient_names(
    session: AsyncSession, agency_id: uuid.UUID, principal_ids: set[uuid.UUID]
) -> dict[str, str]:
    staff = (
        await session.execute(
            select(UserModel.id, UserModel.full_name).where(
                UserModel.id.in_(principal_ids), UserModel.agency_id == agency_id
            )
        )
    ).all()
    passengers = (
        await session.execute(
            select(MobilePassengerIdentityModel.id, PassportSubmissionModel.client_name)
            .join(
                PassportSubmissionModel,
                PassportSubmissionModel.id == MobilePassengerIdentityModel.passenger_submission_id,
            )
            .where(
                MobilePassengerIdentityModel.id.in_(principal_ids),
                MobilePassengerIdentityModel.agency_id == agency_id,
            )
        )
    ).all()
    return {
        str(identifier): name or "Unnamed recipient" for identifier, name in [*staff, *passengers]
    }


async def collect_snapshot(session: AsyncSession, request: GCPushDraft) -> dict[str, Any]:
    now = datetime.now(UTC)
    await active_agency(session, request.agency_id)
    try:
        draft = await require_draft(
            session, agency_id=request.agency_id, draft_id=request.draft_id, lock=True
        )
        if draft.revision != request.expected_revision:
            raise MCPOperationError("gc_push_plan_changed")
        if draft.audience != "selected_groups" or not 1 <= len(draft.group_ids) <= MAX_GROUPS:
            raise MCPOperationError("gc_push_audience_unavailable")
        ids = [uuid.UUID(item) for item in draft.group_ids]
        groups = list(
            await session.scalars(
                select(ClientGroupModel)
                .where(
                    ClientGroupModel.id.in_(ids),
                    ClientGroupModel.agency_id == request.agency_id,
                    ClientGroupModel.deleted_at.is_(None),
                )
                .order_by(ClientGroupModel.id)
                .with_for_update(read=True)
            )
        )
        if len(groups) != len(ids):
            raise MCPOperationError("gc_push_audience_unavailable")
        await session.execute(
            select(GCGroupAccessModel.id)
            .where(
                GCGroupAccessModel.agency_id == request.agency_id,
                GCGroupAccessModel.group_id.in_(ids),
            )
            .order_by(GCGroupAccessModel.id)
            .with_for_update()
        )
        audience = await collect_notification_audience(
            session, agency_id=request.agency_id, group_ids=ids, now=now, max_source_rows=1000
        )
        if {item[0] for item in audience.groups} != set(ids) or not 1 <= len(
            audience.people
        ) <= MAX_PEOPLE:
            raise MCPOperationError("gc_push_audience_unavailable")
        devices: list[dict[str, Any]] = []
        for provider in ("fcm", "apns"):
            current = await registrations_for_grants(
                session,
                agency_id=request.agency_id,
                grants=audience.grants,
                provider_name=provider,
                now=now,
                max_source_rows=MAX_DEVICES,
            )
            devices.extend(
                device_snapshot(row) | {"person_key": person}
                for person, rows in current.items()
                for row in rows
            )
        if len(devices) > MAX_DEVICES:
            raise MCPOperationError("gc_push_audience_unavailable")
        names = await _recipient_names(
            session, request.agency_id, {g.principal_id for g in audience.grants}
        )
        return {
            "request": request.model_dump(mode="json"),
            "agency_id": str(request.agency_id),
            "draft_id": str(draft.id),
            "draft_revision": draft.revision,
            "title": draft.title,
            "body": draft.body,
            "groups": [list(item) for item in audience.groups_as_strings()],
            "grants": [list(grant.signature()) for grant in audience.grants],
            "audience_fingerprint": audience.fingerprint,
            "people": [
                {
                    "person_key": key,
                    "role": grants[0].role,
                    "principal_ids": sorted({str(g.principal_id) for g in grants}),
                    "names": sorted({names[str(g.principal_id)] for g in grants}),
                    "group_ids": sorted({str(g.group_id) for g in grants}),
                }
                for key, grants in sorted(audience.people.items())
            ],
            "devices": sorted(
                devices, key=lambda item: (item["person_key"], item["registration_id"])
            ),
            "recipient_count": len(audience.people),
            "eligible_device_count": len(devices),
            "no_active_registration_count": len(
                set(audience.people) - {d["person_key"] for d in devices}
            ),
        }
    except NotificationWorkflowError as exc:
        raise MCPOperationError("gc_push_audience_unavailable") from exc
