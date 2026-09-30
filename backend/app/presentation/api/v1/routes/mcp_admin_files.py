"""Bounded management metadata across exports, source imports and header media."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import DateTime, Uuid, case, literal, null, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Subquery

from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel as Artifact
from app.infrastructure.database.mcp_contact_import_models import (
    MCPContactImportUploadModel as Contacts,
)
from app.infrastructure.database.mcp_operation_models import MCPOperationModel as Operation
from app.infrastructure.database.mcp_whatsapp_media_models import (
    MCPWhatsAppHeaderMediaModel as Media,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.dependencies.mcp import require_mcp_management
from app.presentation.mcp.management_audit import MCPManagementAuditRoute

router = APIRouter(dependencies=[Depends(require_mcp_management)], route_class=MCPManagementAuditRoute)


def file_projection(now: datetime) -> Subquery:
    # Each branch selects only management-safe metadata. Locators, provider IDs,
    # source cells and private object keys never reach this projection.
    artifacts = select(
        Artifact.id, literal("artifact").label("kind"), Artifact.grant_id.label("connection_id"),
        Artifact.agency_id, Artifact.group_id, null().cast(Uuid).label("broadcast_id"),
        Artifact.direction, Artifact.purpose, Artifact.filename, Artifact.byte_size, Artifact.sha256,
        Artifact.created_at, Artifact.expires_at, Artifact.delivered_at,
        null().cast(DateTime(timezone=True)).label("attempt_deadline"), Artifact.ingestion_operation_id.label("operation_id"),
        case(
            (Artifact.delivered_at.is_not(None), "delivered"),
            (Operation.status == "succeeded", "ingested"),
            (Operation.status == "failed", "ingestion_failed"),
            (Operation.status == "unknown", "unknown"),
            (Operation.status.in_(("queued", "running")), Operation.status),
            (Artifact.expires_at <= now, "expired"),
            else_="available",
        ).label("status"),
    ).outerjoin(Operation, Operation.id == Artifact.ingestion_operation_id)
    contacts = select(
        Contacts.id, literal("contact_workbook"), Contacts.original_grant_id,
        Contacts.agency_id, null(), Contacts.broadcast_id, literal("upload"), literal("contact_workbook"),
        Contacts.filename, Contacts.byte_size, Contacts.sha256, Contacts.created_at, Contacts.expires_at,
        null(), null(), Contacts.consumed_operation_id,
        case((Contacts.consumed_at.is_not(None), "imported"),
             (Contacts.expires_at <= now, "expired"), else_="staged"),
    )
    media = select(
        Media.id, literal("whatsapp_header"), Media.original_grant_id,
        Media.agency_id, null(), Media.broadcast_id, literal("upload"), literal("whatsapp_header"),
        Media.filename, Media.original_byte_size, Media.original_sha256, Media.created_at, Media.expires_at,
        null(), Media.attempt_expires_at, null(),
        case((Media.status.in_(("failed", "unknown")), Media.status),
             (Media.status == "uploading", "uploading"),
             (Media.expires_at <= now, "expired"), else_=Media.status),
    )
    return union_all(artifacts, contacts, media).subquery()


@router.get("/artifacts")
async def artifacts(
    request: Request,
    offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    if request.app.state.settings.mcp.read_only_mode:
        raise HTTPException(403, "MCP file controls are unavailable in this read-only deployment")
    projection = file_projection(datetime.now(UTC))
    rows = (await session.execute(select(projection)
        .order_by(projection.c.created_at.desc(), projection.c.id.desc(), projection.c.kind)
        .offset(offset).limit(limit + 1))).mappings().all()
    identifiers = ("id", "connection_id", "agency_id", "group_id", "broadcast_id", "operation_id")
    items = []
    for row in rows[:limit]:
        item = dict(row)
        for name in identifiers:
            item[name] = str(item[name]) if item[name] is not None else None
        items.append(item)
    return {"items": items, "next_offset": offset + limit if len(rows) > limit else None}
