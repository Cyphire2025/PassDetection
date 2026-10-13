"""Directory writes and bounded keyset search over the existing company table.

Memory is O(page_size); keyset traversal avoids offset work. Ordered lookups
use agency/status/name/id indexes. PostgreSQL contains search uses pg_trgm;
one-character searches may still scan a tenant and should be measured separately.
All writes are flush-only so the caller's transaction includes the audit event.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import (
    COMPANY_ADMIN_ROLES,
    company_agency_scope,
    require_company,
)
from app.application.mcp.read_cursor import MCPReadCursor
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError, ConflictError, ValidationError
from app.infrastructure.database.gc_mobile_models import (
    ClientOrganizationModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


def normalize_company_name(name: str) -> tuple[str, str]:
    display = " ".join(name.split())
    if not display or len(display) > 255 or len(display.casefold()) > 255:
        raise ValidationError("Company name must contain 1 to 255 characters", field="name")
    return display, display.casefold()


async def create_company(
    session: AsyncSession, *, user: User, agency_id: uuid.UUID | None,
    name: str, external_reference: str | None = None,
) -> ClientOrganizationModel:
    if user.role not in COMPANY_ADMIN_ROLES:
        raise AuthorizationError()
    scope = company_agency_scope(user, agency_id)
    display, normalized = normalize_company_name(name)
    now = datetime.now(UTC)
    company = ClientOrganizationModel(
        id=uuid.uuid4(), agency_id=scope, name=display, normalized_name=normalized,
        external_reference=external_reference, status="active", revision=1,
        created_by_user_id=user.id, updated_by_user_id=user.id, created_at=now, updated_at=now,
    )
    try:
        async with session.begin_nested():
            session.add(company)
            await session.flush()
    except IntegrityError as exc:
        raise ConflictError("Company name or external reference is already in use") from exc
    await _audit(session, user, company, "company.created")
    return company


async def update_company(
    session: AsyncSession, *, user: User, company_id: uuid.UUID,
    agency_id: uuid.UUID | None, expected_revision: int, changes: dict[str, object],
) -> ClientOrganizationModel:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id, lock=True)
    _check_revision(company, expected_revision)
    try:
        async with session.begin_nested():
            if "name" in changes:
                company.name, company.normalized_name = normalize_company_name(str(changes["name"]))
            if "external_reference" in changes:
                reference = changes["external_reference"]
                company.external_reference = str(reference) if reference is not None else None
            if "status" in changes:
                if changes["status"] not in ("active", "inactive"):
                    raise ValidationError("Invalid company status")
                company.status = str(changes["status"])
            company.revision += 1
            company.updated_by_user_id = user.id
            company.updated_at = datetime.now(UTC)
            await session.flush()
    except IntegrityError as exc:
        raise ConflictError("Company name or external reference is already in use") from exc
    await _audit(session, user, company, "company.updated")
    return company


async def delete_company(
    session: AsyncSession, *, user: User, company_id: uuid.UUID,
    agency_id: uuid.UUID | None, expected_revision: int,
) -> None:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id, lock=True)
    _check_revision(company, expected_revision)
    from app.application.companies.removal import detach_company_groups

    preserved = await detach_company_groups(session, company=company, user=user)
    company.status = "deleted"
    company.deleted_at = datetime.now(UTC)
    company.updated_at = company.deleted_at
    company.updated_by_user_id = user.id
    company.revision += 1
    await session.flush()
    await AuditLogRepository(session).record(
        action="company.deleted", entity_type="client_organization", entity_id=str(company.id),
        agency_id=company.agency_id, user_id=user.id, actor_email=user.email,
        metadata={"status": company.status, "revision": company.revision, **preserved},
    )


async def search_companies(
    session: AsyncSession, *, user: User, agency_id: uuid.UUID, search: str,
    status: str, cursor: str | None, page_size: int, secret: str,
) -> tuple[list[ClientOrganizationModel], str | None, bool]:
    query = " ".join(search.split()).casefold()
    codec = MCPReadCursor(secret, "company-directory-v1")
    try:
        state = codec.read(cursor, {"user": user.id, "agency": agency_id, "search": query, "status": status})
    except ValueError as exc:
        raise ValidationError(str(exc), field="cursor") from exc
    filters = [ClientOrganizationModel.agency_id == agency_id, ClientOrganizationModel.status != "deleted"]
    if status != "all":
        filters.append(ClientOrganizationModel.status == status)
    if query:
        filters.append(ClientOrganizationModel.normalized_name.contains(query, autoescape=True))
    if "after_id" in state:
        after_name = state.get("after_name")
        if not isinstance(after_name, str):
            raise ValidationError("Invalid directory cursor", field="cursor")
        filters.append(or_(ClientOrganizationModel.normalized_name > after_name, and_(
            ClientOrganizationModel.normalized_name == after_name,
            ClientOrganizationModel.id > uuid.UUID(state["after_id"]),
        )))
    items = list((await session.scalars(select(ClientOrganizationModel).where(*filters).order_by(
        ClientOrganizationModel.normalized_name.asc(), ClientOrganizationModel.id.asc(),
    ).limit(page_size + 1))).all())
    has_more = len(items) > page_size
    items = items[:page_size]
    next_cursor = None
    if has_more:
        last = items[-1]
        next_cursor = codec.encode({**state, "after_name": last.normalized_name,
                                    "after_id": str(last.id), "after_created_at": last.created_at.isoformat()})
    return items, next_cursor, has_more


def _check_revision(company: ClientOrganizationModel, expected: int) -> None:
    if company.revision != expected:
        raise ConflictError("Company changed; refresh and retry")


async def _audit(session: AsyncSession, user: User, company: ClientOrganizationModel, action: str) -> None:
    await AuditLogRepository(session).record(
        action=action, entity_type="client_organization", entity_id=str(company.id),
        agency_id=company.agency_id, user_id=user.id, actor_email=user.email,
        metadata={"status": company.status, "revision": company.revision},
    )
