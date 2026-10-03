"""Bounded observations of existing QR credentials and recorded attendance."""

from __future__ import annotations

import base64
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.read_context import MCPReadContext
from app.core.config.settings import Settings
from app.domain.entities.entities import OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES, ClientGroup
from app.infrastructure.database.models import (
    AttendanceRecordModel,
    AttendanceSessionModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
)
from app.infrastructure.qr.approved_passenger_qr_issuer import qr_status
from app.infrastructure.qr.qr_image_renderer import render_attendance_qr_png
from app.infrastructure.repositories.operational_roster import operational_roster_member


class MCPTourEvidenceReadService(MCPReadContext):
    def __init__(self, session: AsyncSession, settings: Settings):
        super().__init__(
            session, cursor_secret=settings.app_secret_key, namespace="mcp-tour-evidence-v1"
        )

    async def scope(
        self, principal: MCPPrincipal, agency_id: UUID, group_id: UUID, page_size: int = 1
    ) -> ClientGroup:
        actor = await self._actor(principal.user_id, page_size)
        if actor.agency_id != agency_id:
            raise MCPAuthError("access_denied", 403)
        return await self._group(actor, group_id, agency_id, False)

    async def qr(
        self, principal: MCPPrincipal, *, agency_id: UUID, group_id: UUID, passenger_id: UUID
    ) -> dict[str, Any]:
        await self.scope(principal, agency_id, group_id)
        passenger = await self.session.execute(
            select(
                PassportSubmissionModel.id,
                func.substr(PassportSubmissionModel.client_name, 1, 255).label("name"),
            ).where(
                PassportSubmissionModel.id == passenger_id,
                PassportSubmissionModel.agency_id == agency_id,
                PassportSubmissionModel.group_id == group_id,
                PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
                operational_roster_member(),
            )
        )
        row = passenger.one_or_none()
        if row is None:
            raise ValueError("Passenger is unavailable in the current group")
        token = await self.session.scalar(
            select(PassengerQRTokenModel)
            .where(
                PassengerQRTokenModel.passenger_id == passenger_id,
                PassengerQRTokenModel.agency_id == agency_id,
            )
            .order_by(
                PassengerQRTokenModel.token_version.desc(), PassengerQRTokenModel.created_at.desc()
            )
            .limit(1)
        )
        status = qr_status(token)
        image = None
        if token and status in {"active", "inactive"} and token.qr_payload:
            image = render_attendance_qr_png(token.qr_payload)
            if len(image) > 256 * 1024:
                raise ValueError("QR image exceeds the bound")
        return {
            "agency_id": str(agency_id),
            "group_id": str(group_id),
            "passenger_id": str(passenger_id),
            "passenger_name": row.name,
            "qr_status": status,
            "token_version": token.token_version if token else None,
            "expires_at": token.expires_at.isoformat() if token else None,
            "qr_image_png": base64.b64encode(image).decode("ascii") if image else None,
            "read_only": True,
            "credential_created": False,
            "content_trust": "untrusted_business_data",
        }

    async def attendance(
        self,
        principal: MCPPrincipal,
        *,
        agency_id: UUID,
        group_id: UUID,
        activity_id: UUID,
        page_size: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        await self.scope(principal, agency_id, group_id, page_size)
        activity = await self.session.scalar(
            select(AttendanceSessionModel).where(
                AttendanceSessionModel.id == activity_id,
                AttendanceSessionModel.agency_id == agency_id,
                AttendanceSessionModel.group_id == group_id,
            )
        )
        if activity is None:
            raise ValueError("Attendance activity is unavailable")
        canonical_id = activity.canonical_session_id
        state, query = self._state(
            cursor,
            actor=principal.user_id,
            agency=agency_id,
            group=group_id,
            activity=activity_id,
            canonical_activity=canonical_id,
            page_size=page_size,
        )
        record = AttendanceRecordModel
        statement = (
            select(
                record.id,
                record.passenger_id,
                record.coordinator_user_id,
                record.session_id,
                record.scanned_at,
                record.sync_source,
                record.created_at,
                func.substr(PassportSubmissionModel.client_name, 1, 255).label("passenger_name"),
            )
            .join(AttendanceSessionModel, AttendanceSessionModel.id == record.session_id)
            .outerjoin(
                PassportSubmissionModel,
                (PassportSubmissionModel.id == record.passenger_id)
                & (PassportSubmissionModel.agency_id == agency_id)
                & (PassportSubmissionModel.group_id == group_id)
                & operational_roster_member(),
            )
            .where(
                record.agency_id == agency_id,
                AttendanceSessionModel.agency_id == agency_id,
                AttendanceSessionModel.group_id == group_id,
                AttendanceSessionModel.canonical_session_id == canonical_id,
                record.created_at <= query["cutoff"],
            )
        )
        if query["after"]:
            created_at, identifier = query["after"]
            statement = statement.where(
                or_(
                    record.created_at > created_at,
                    (record.created_at == created_at) & (record.id > identifier),
                )
            )
        rows = [
            dict(row)
            for row in (
                await self.session.execute(
                    statement.order_by(record.created_at, record.id).limit(page_size + 1)
                )
            ).mappings()
        ]
        result = self._result(
            rows,
            state,
            page_size,
            "Existing recorded evidence only; rows may include alias activity events for the same passenger. Use the canonical attendance summary for distinct present counts. No physical presence is inferred or fabricated.",
        )
        result.update(
            agency_id=str(agency_id),
            group_id=str(group_id),
            canonical_activity_id=str(canonical_id),
            requested_activity_id=str(activity_id),
            read_only=True,
        )
        return result
