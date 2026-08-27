"""Bounded response projection helpers shared by GC App history routes."""

from __future__ import annotations

from collections.abc import Iterable

from app.infrastructure.database.gc_mobile_models import MobileDeviceSessionModel
from app.infrastructure.database.models import AuditLogModel
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerSessionResponse,
    GCAppAuditResponse,
)


def client_manager_session_responses(
    sessions: Iterable[MobileDeviceSessionModel],
) -> list[ClientManagerSessionResponse]:
    return [
        ClientManagerSessionResponse(
            id=item.id,
            platform=item.platform,
            app_version=item.app_version,
            status=item.status,
            last_seen_at=item.last_seen_at,
            created_at=item.created_at,
            expires_at=item.expires_at,
            revoked_at=item.revoked_at,
        )
        for item in sessions
    ]


def gc_app_audit_responses(logs: Iterable[AuditLogModel]) -> list[GCAppAuditResponse]:
    return [
        GCAppAuditResponse(
            id=item.id,
            action=item.action,
            entity_type=item.entity_type,
            entity_id=item.entity_id,
            actor_email=item.actor_email,
            metadata=item.metadata_json or {},
            created_at=item.created_at,
        )
        for item in logs
    ]
