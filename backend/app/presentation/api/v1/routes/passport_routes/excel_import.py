"""Passport excel import: focused workflow boundary."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.authorization_policy import AuthorizationPolicy
from app.core.config.settings import get_settings
from app.domain.entities.entities import ClientGroup, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.imports.passport_excel_importer import (
    ImportedPassportRow,
    PassportExcelImporter,
    PassportExcelImportError,
)
from app.infrastructure.mobile_group_capacity import SqlAlchemyGroupPassengerCapacityGuard
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.schemas.passport_schemas import ImportPassportGroupResponse
from app.presentation.dependencies.auth import get_current_active_user

from .constants import (
    PASSPORT_EXCEL_UPLOAD_READ_CHUNK_BYTES,
    _apply_passport_excel_row_to_submission,
    _build_passport_excel_existing_indexes,
    _deduplicate_passport_excel_rows,
    _PassportExcelImportConflict,
    _resolve_existing_passport_excel_submission,
)

router = APIRouter()


async def _read_bounded_passport_excel_upload(
    file: UploadFile,
    *,
    max_bytes: int,
) -> bytes:
    """Read one workbook without allowing an unbounded multipart allocation."""

    payload = bytearray()
    try:
        while True:
            remaining = max_bytes + 1 - len(payload)
            if remaining <= 0:
                break
            chunk = await file.read(min(PASSPORT_EXCEL_UPLOAD_READ_CHUNK_BYTES, remaining))
            if not chunk:
                break
            payload.extend(chunk)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read the Excel file",
        ) from exc

    if len(payload) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                "The Excel file is too large; use a file no larger than "
                f"{max_bytes // (1024 * 1024)} MB."
            ),
        )
    return bytes(payload)


async def _parse_passport_excel_rows(content: bytes) -> list[ImportedPassportRow]:
    """Keep CPU-bound OpenXML parsing away from the async request loop."""

    return await asyncio.to_thread(PassportExcelImporter().import_rows, content)


async def _lock_passport_excel_group_import(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> bool:
    locked_group_id = await session.scalar(
        select(ClientGroupModel.id)
        .where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
        )
        .with_for_update()
    )
    return locked_group_id is not None


async def _lock_and_reauthorize_passport_excel_import(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    expected_agency_id: uuid.UUID,
    user_id: uuid.UUID,
) -> tuple[User, ClientGroup]:
    """Lock the group, then refresh every authorization input atomically."""

    group_locked = await _lock_passport_excel_group_import(
        session,
        group_id=group_id,
        agency_id=expected_agency_id,
    )
    if not group_locked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )

    refreshed_user = await UserRepository(session).get_by_id(user_id)
    if (
        refreshed_user is None
        or not refreshed_user.is_active
        or refreshed_user.agency_id is None
        or refreshed_user.role == UserRole.AGENCY_COORDINATOR
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    refreshed_group = await ClientGroupRepository(session).get_by_id(group_id)
    if refreshed_group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    if (
        refreshed_group.agency_id != expected_agency_id
        or refreshed_user.agency_id != refreshed_group.agency_id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    try:
        await AuthorizationPolicy(session).require_export_data(
            refreshed_user,
            refreshed_group,
        )
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    return refreshed_user, refreshed_group


@router.post(
    "/groups/{group_id}/import.xlsx",
    response_model=ImportPassportGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import passport submissions into a client group from Excel",
)
async def import_passports_by_group(
    group_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ImportPassportGroupResponse:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    group_repo = ClientGroupRepository(session)
    group = await group_repo.get_by_id(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    expected_agency_id = group.agency_id

    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Please upload an .xlsx Excel file"
        )

    # Authentication and the initial group authorization are read-only. End
    # that transaction before workbook parsing so a CPU-bound file cannot hold
    # a database snapshot or connection open.
    await session.rollback()

    try:
        content = await _read_bounded_passport_excel_upload(
            file,
            max_bytes=get_settings().upload_max_file_size_bytes,
        )
        rows = await _parse_passport_excel_rows(content)
        # Workbook-only normalization and duplicate detection can be material
        # for a 10k-row import. Keep it off the event loop and, critically,
        # outside the tenant/group lock acquired for persistence below.
        unique_rows = await asyncio.to_thread(_deduplicate_passport_excel_rows, rows)
    except PassportExcelImportError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except _PassportExcelImportConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to read the Excel file"
        )

    # Serialize only the short read/merge/write section for this tenant-owned
    # group. Parsing happens before the lock so a large workbook never extends
    # lock duration, while concurrent imports cannot both create the same row.
    try:
        current_user, group = await _lock_and_reauthorize_passport_excel_import(
            session,
            group_id=group_id,
            expected_agency_id=expected_agency_id,
            user_id=current_user.id,
        )
    except HTTPException:
        await session.rollback()
        raise

    result = await session.execute(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == group.agency_id,
        )
    )
    existing_submissions = list(result.scalars().all())
    try:
        existing_indexes = _build_passport_excel_existing_indexes(existing_submissions)
        resolved_rows: list[tuple[ImportedPassportRow, PassportSubmissionModel | None]] = []
        resolved_submission_ids: set[uuid.UUID] = set()
        for row in unique_rows:
            existing = _resolve_existing_passport_excel_submission(
                row,
                existing_indexes,
            )
            if existing is not None:
                if existing.id in resolved_submission_ids:
                    raise _PassportExcelImportConflict(
                        "Multiple workbook rows resolve to the same existing "
                        "passenger through conflicting identifiers."
                    )
                resolved_submission_ids.add(existing.id)
            resolved_rows.append((row, existing))
    except _PassportExcelImportConflict as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    new_passenger_count = sum(1 for _row, existing in resolved_rows if existing is None)
    if new_passenger_count:
        await SqlAlchemyGroupPassengerCapacityGuard(session).assert_available(
            agency_id=group.agency_id,
            group_id=group.id,
            additional_passengers=new_passenger_count,
        )

    now = datetime.now(tz=UTC)
    models: list[PassportSubmissionModel] = []
    updated_count = 0
    for row, existing in resolved_rows:
        if existing is not None:
            _apply_passport_excel_row_to_submission(existing, row, now=now)
            updated_count += 1
            continue

        submission_id = uuid.uuid4()
        models.append(
            PassportSubmissionModel(
                id=submission_id,
                group_id=group.id,
                agency_id=group.agency_id,
                client_name=row.client_name,
                client_email=row.client_email,
                client_phone=row.client_phone,
                departure_city=row.departure_city,
                nearest_domestic_airport=row.nearest_domestic_airport,
                image_s3_key=f"excel-imports/{group.id}/{submission_id}.placeholder",
                status="client_submitted",
                confirmed_fields=row.confirmed_fields or None,
                extracted_fields=row.confirmed_fields or None,
                staff_metadata=row.staff_metadata or None,
                overall_confidence=1.0 if row.confirmed_fields else None,
                confidence_score={
                    "source": "excel_import",
                    "row_number": row.row_number,
                    "source_sheet": row.worksheet_name,
                },
                client_reviewed_at=now,
                created_at=now,
                updated_at=now,
            )
        )

    if models:
        session.add_all(models)
    if models or updated_count:
        changed_submission_ids = [model.id for model in models]
        changed_submission_ids.extend(
            existing.id for _row, existing in resolved_rows if existing is not None
        )
        await propagate_mobile_passenger_change(
            session,
            agency_id=group.agency_id,
            group_id=group.id,
            passenger_submission_ids=changed_submission_ids,
            actor_user_id=current_user.id,
            change_kind="profile",
        )
        await AuditLogRepository(session).record(
            action="passport_group_imported",
            entity_type="client_group",
            entity_id=str(group_id),
            agency_id=group.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "imported_count": len(models),
                "updated_count": updated_count,
                "filename": file.filename,
            },
        )
        await session.commit()
    else:
        # Release the group row lock before returning a no-op result.
        await session.rollback()

    return ImportPassportGroupResponse(
        imported_count=len(models),
        updated_count=updated_count,
        skipped_count=max(len(rows) - len(models) - updated_count, 0),
    )
