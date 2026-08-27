"""
Audit Log Routes
================
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogFilters,
    AuditLogRepository,
    AuditResult,
    InvalidAuditCursorError,
    audit_log_result,
)
from app.presentation.api.v1.schemas.audit_log_schemas import (
    AuditLogListItemResponse,
    AuditLogPageResponse,
)
from app.presentation.api.v1.schemas.operations_schemas import AuditLogResponse
from app.presentation.dependencies.auth import require_role
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()

AUDIT_PAGE_MAX_SIZE = 100
AUDIT_EXPORT_MAX_ROWS = 10_000
AUDIT_EXPORT_MAX_RANGE = timedelta(days=31)
AUDIT_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN]


@router.get(
    "",
    response_model=list[AuditLogResponse],
    status_code=status.HTTP_200_OK,
    summary="List audit logs for the current administrative scope",
)
async def list_audit_logs(
    request: Request,
    current_user: User = Depends(require_role(AUDIT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
    skip: int = Query(default=0, ge=0, le=1_000_000),
    limit: int = Query(default=100, ge=1, le=AUDIT_PAGE_MAX_SIZE),
) -> list[AuditLogResponse]:
    agency_id = None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id
    repository = AuditLogRepository(session)
    logs = await repository.list_by_agency(agency_id, skip=skip, limit=limit)
    response = [
        AuditLogResponse(
            id=log.id,
            agency_id=log.agency_id,
            user_id=log.user_id,
            actor_email=log.actor_email,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            ip_address=log.ip_address,
            metadata=log.metadata_json,
            created_at=log.created_at,
        )
        for log in logs
    ]
    await _record_audit_access(
        repository,
        request=request,
        current_user=current_user,
        agency_id=agency_id,
        action="audit.logs.legacy_viewed",
        entity_id=str(agency_id) if agency_id else None,
        filter_names=("offset",),
        returned_count=len(response),
        has_more=len(response) == limit,
    )
    return response


@router.get(
    "/page",
    response_model=AuditLogPageResponse,
    status_code=status.HTTP_200_OK,
    summary="Page through the authorized audit ledger with stable keyset ordering",
)
async def page_audit_logs(
    request: Request,
    cursor: str | None = Query(default=None, max_length=2048),
    page_size: int = Query(default=50, ge=1, le=AUDIT_PAGE_MAX_SIZE),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    actor: str | None = Query(default=None, max_length=255),
    event_type: str | None = Query(default=None, max_length=80),
    entity_type: str | None = Query(default=None, max_length=80),
    entity_id: str | None = Query(default=None, max_length=128),
    result: AuditResult | None = Query(default=None),
    agency_id: uuid.UUID | None = Query(default=None),
    current_user: User = Depends(require_role(AUDIT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> AuditLogPageResponse | JSONResponse:
    scope = _audit_scope(current_user, agency_id)
    filters = _audit_filters(
        agency_id=scope,
        start_at=start_at,
        end_at=end_at,
        actor=actor,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        result=result,
    )
    repository = AuditLogRepository(session)
    try:
        page = await repository.list_page(filters, cursor=cursor, limit=page_size)
    except InvalidAuditCursorError:
        await _record_audit_access(
            repository,
            request=request,
            current_user=current_user,
            agency_id=scope,
            action="audit.logs.view_blocked",
            entity_id=str(scope) if scope else None,
            filter_names=_active_filter_names(filters),
            returned_count=0,
            has_more=False,
            result="blocked",
        )
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": {
                    "code": "AUDIT_CURSOR_INVALID",
                    "message": "The audit cursor is invalid for these filters.",
                }
            },
            headers={"Cache-Control": "private, no-store"},
        )
    response = AuditLogPageResponse(
        items=[_audit_list_item(log) for log in page.items],
        has_more=page.has_more,
        next_cursor=page.next_cursor,
        incomplete=page.has_more,
        page_size=page_size,
    )
    await _record_audit_access(
        repository,
        request=request,
        current_user=current_user,
        agency_id=scope,
        action="audit.logs.viewed",
        entity_id=str(scope) if scope else None,
        filter_names=_active_filter_names(filters),
        returned_count=len(response.items),
        has_more=response.has_more,
    )
    return response


@router.get(
    "/export.csv",
    response_class=Response,
    status_code=status.HTTP_200_OK,
    summary="Export a bounded authorized audit-ledger time range",
)
async def export_audit_logs(
    request: Request,
    start_at: datetime = Query(...),
    end_at: datetime = Query(...),
    actor: str | None = Query(default=None, max_length=255),
    event_type: str | None = Query(default=None, max_length=80),
    entity_type: str | None = Query(default=None, max_length=80),
    entity_id: str | None = Query(default=None, max_length=128),
    result: AuditResult | None = Query(default=None),
    agency_id: uuid.UUID | None = Query(default=None),
    current_user: User = Depends(require_role(AUDIT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    scope = _audit_scope(current_user, agency_id)
    filters = _audit_filters(
        agency_id=scope,
        start_at=start_at,
        end_at=end_at,
        actor=actor,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        result=result,
    )
    if _utc(end_at) - _utc(start_at) > AUDIT_EXPORT_MAX_RANGE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Audit exports may cover at most 31 days",
        )
    repository = AuditLogRepository(session)
    logs, truncated = await repository.list_for_export(
        filters,
        limit=AUDIT_EXPORT_MAX_ROWS,
    )
    content = _audit_csv(logs)
    await _record_audit_access(
        repository,
        request=request,
        current_user=current_user,
        agency_id=scope,
        action="audit.logs.exported",
        entity_id=str(scope) if scope else None,
        filter_names=_active_filter_names(filters),
        returned_count=len(logs),
        has_more=truncated,
    )
    filename_date = datetime.now(tz=UTC).date().isoformat()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": (f'attachment; filename="audit-logs-{filename_date}.csv"'),
            "X-Audit-Export-Truncated": "true" if truncated else "false",
        },
    )


def _audit_scope(
    current_user: User,
    requested_agency_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if current_user.role == UserRole.SUPER_ADMIN:
        return requested_agency_id
    if current_user.agency_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Audit scope is unavailable",
        )
    if requested_agency_id is not None and requested_agency_id != current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Audit scope is unavailable",
        )
    return current_user.agency_id


def _audit_filters(
    *,
    agency_id: uuid.UUID | None,
    start_at: datetime | None,
    end_at: datetime | None,
    actor: str | None,
    event_type: str | None,
    entity_type: str | None,
    entity_id: str | None,
    result: AuditResult | None,
) -> AuditLogFilters:
    if start_at is not None and end_at is not None and _utc(start_at) > _utc(end_at):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Audit start time must not be after the end time",
        )
    return AuditLogFilters(
        agency_id=agency_id,
        start_at=_utc(start_at) if start_at else None,
        end_at=_utc(end_at) if end_at else None,
        actor=_normalized_filter(actor),
        event_type=_normalized_filter(event_type),
        entity_type=_normalized_filter(entity_type),
        entity_id=_normalized_filter(entity_id),
        result=result,
    )


def _audit_list_item(log: AuditLogModel) -> AuditLogListItemResponse:
    return AuditLogListItemResponse(
        id=log.id,
        agency_id=log.agency_id,
        user_id=log.user_id,
        actor_email=log.actor_email,
        event_type=log.action,
        entity_type=log.entity_type,
        entity_id=log.entity_id,
        result=audit_log_result(log),
        created_at=log.created_at,
    )


async def _record_audit_access(
    repository: AuditLogRepository,
    *,
    request: Request,
    current_user: User,
    agency_id: uuid.UUID | None,
    action: str,
    entity_id: str | None,
    filter_names: tuple[str, ...],
    returned_count: int,
    has_more: bool,
    result: AuditResult = "success",
) -> None:
    await repository.record(
        action=action,
        entity_type="audit_ledger",
        agency_id=agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=entity_id,
        ip_address=trusted_client_ip(request),
        result=result,
        metadata={
            "filters": list(filter_names),
            "returned_count": returned_count,
            "incomplete": has_more,
        },
    )


def _active_filter_names(filters: AuditLogFilters) -> tuple[str, ...]:
    fields = (
        ("start_at", filters.start_at),
        ("end_at", filters.end_at),
        ("actor", filters.actor),
        ("event_type", filters.event_type),
        ("entity_type", filters.entity_type),
        ("entity_id", filters.entity_id),
        ("result", filters.result),
        ("agency_id", filters.agency_id),
    )
    return tuple(name for name, value in fields if value is not None)


def _audit_csv(logs: list[AuditLogModel]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        (
            "id",
            "created_at",
            "agency_id",
            "actor",
            "event_type",
            "entity_type",
            "entity_id",
            "result",
        )
    )
    for item in logs:
        log = _audit_list_item(item)
        writer.writerow(
            tuple(
                _safe_csv_cell(value)
                for value in (
                    log.id,
                    log.created_at,
                    log.agency_id,
                    log.actor_email or "system",
                    log.event_type,
                    log.entity_type,
                    log.entity_id,
                    log.result,
                )
            )
        )
    return buffer.getvalue()


def _safe_csv_cell(value: object) -> str:
    if value is None:
        return ""
    rendered = value.isoformat() if isinstance(value, datetime) else str(value)
    if rendered.lstrip().startswith(("=", "+", "-", "@")):
        return f"'{rendered}"
    return rendered


def _normalized_filter(value: str | None) -> str | None:
    normalized = " ".join(value.split()) if value else ""
    return normalized or None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
