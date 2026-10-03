"""Native staged originals retain immutable target/lane authority beyond handoff expiry."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.authorization import MCPPrincipal
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_native_transfer_models import MCPNativeTransferModel


async def require_native_pdf_source(
    session: AsyncSession,
    principal: MCPPrincipal,
    source: MCPArtifactModel,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    document_type: str,
    lock: bool = False,
) -> None:
    """Legacy protected artifacts remain supported; native sources keep their prepared lane.

    A completed ticket's transport expiry never shortens the source lifetime.
    Explicit receipt recovery may use a new grant for the same current identity,
    while the original source/ticket grant association remains exact.
    """
    statement = (
        select(MCPNativeTransferModel)
        .where(MCPNativeTransferModel.artifact_id == source.id)
        .limit(2)
    )
    if lock:
        statement = statement.with_for_update(read=True)
    tickets = (await session.scalars(statement.execution_options(populate_existing=True))).all()
    if not tickets:
        return
    grant = await session.get(MCPGrantModel, principal.grant_id, populate_existing=True)
    if len(tickets) != 1 or grant is None:
        raise ArtifactError("Native staged PDF binding is unavailable", 404)
    ticket = tickets[0]
    if (
        ticket.kind != "upload_pdf"
        or ticket.purpose != "document_pdf"
        or ticket.status != "completed"
        or ticket.completed_at is None
        or ticket.claim_id is not None
        or ticket.claim_expires_at is not None
        or ticket.original_grant_id != source.grant_id
        or ticket.user_id != source.user_id
        or ticket.user_id != principal.user_id
        or ticket.security_version != grant.security_version
        or source.direction != "upload"
        or source.purpose != "group_document_pdf"
        or (ticket.agency_id, ticket.group_id, ticket.document_type)
        != (agency_id, group_id, document_type)
        or (source.agency_id, source.group_id) != (agency_id, group_id)
        or (ticket.byte_size, ticket.sha256, ticket.media_type, ticket.filename)
        != (source.byte_size, source.sha256, source.media_type, source.filename)
        or ticket.media_type != "application/pdf"
    ):
        raise ArtifactError(
            "Native staged PDF does not match its prepared target and document lane", 404
        )
