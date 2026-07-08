"""
Passport Routes — /api/v1/passports
===================================
"""

from __future__ import annotations

import uuid
import io

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.application.use_cases.passports.confirm_passport_submission_use_case import ConfirmPassportSubmissionUseCase
from app.application.use_cases.passports.client_submit_passport_use_case import ClientSubmitPassportUseCase
from app.application.use_cases.passports.get_passport_submission_use_case import GetPassportSubmissionUseCase
from app.application.use_cases.passports.list_passport_group_summaries_use_case import ListPassportGroupSummariesUseCase
from app.application.use_cases.passports.list_passport_submissions_use_case import ListPassportSubmissionsUseCase
from app.application.use_cases.passports.list_passport_submissions_by_group_use_case import ListPassportSubmissionsByGroupUseCase
from app.application.use_cases.passports.reextract_passport_submission_use_case import ReextractPassportSubmissionUseCase
from app.application.use_cases.passports.retry_public_passport_extraction_use_case import RetryPublicPassportExtractionUseCase
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError, PassDetectionError, EntityNotFoundError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.models import ClientGroupModel, ManagerGroupAccessModel, PassportSubmissionModel
from app.infrastructure.export.passport_excel_exporter import PassportExcelExporter
from app.infrastructure.ocr.passport_extraction_service import PassportExtractionService
from app.infrastructure.processing.dispatcher import PassportProcessingDispatcher
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_submission_repository import PassportSubmissionRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.security.upload_validator import UploadValidator
from app.infrastructure.repositories.notification_repository import NotificationRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.passport_schemas import (
    ClientSubmitPassportRequest,
    ConfirmPassportSubmissionRequest,
    ExportSelectedGroupsRequest,
    ExportSelectedPassportsRequest,
    PassportGroupSummaryResponse,
    PassportSubmissionResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()


def _owner_scope_for(user: User) -> uuid.UUID | None:
    return user.id if user.role == UserRole.AGENCY_STAFF else None


def _submitted_statuses() -> tuple[str, str]:
    return ("client_submitted", "confirmed")


def _apply_manager_visibility(stmt, current_user: User):  # type: ignore[no-untyped-def]
    if current_user.role != UserRole.AGENCY_STAFF:
        return stmt
    return stmt.outerjoin(
        ManagerGroupAccessModel,
        (ManagerGroupAccessModel.group_id == ClientGroupModel.id)
        & (ManagerGroupAccessModel.manager_id == current_user.id),
    ).where(
        or_(
            ClientGroupModel.created_by_user_id == current_user.id,
            ManagerGroupAccessModel.manager_id == current_user.id,
        )
    )


async def _ensure_group_owner_scope(
    group_id: uuid.UUID,
    current_user: User,
    group_repo: ClientGroupRepository,
) -> None:
    owner_scope = _owner_scope_for(current_user)
    if not owner_scope:
        return
    group = await group_repo.get_by_id(group_id)
    if not group or not await group_repo.manager_can_access(group_id, owner_scope):
        raise AuthorizationError("You do not have access to this manager's group")


async def _response_from_dto(
    result: PassportSubmissionOutputDTO,
    *,
    session: AsyncSession,
) -> PassportSubmissionResponse:
    image_url = await MinioStorageRepository().get_presigned_url(result.image_s3_key)
    payload = {**result.__dict__, "image_url": image_url}
    if not payload.get("processing_job_id"):
        job = await PassportProcessingJobRepository(session).latest_for_submission(result.id)
        if job:
            payload.update(
                {
                    "processing_job_id": job.id,
                    "processing_job_status": job.status.value,
                    "processing_progress": job.progress,
                    "processing_stage": job.current_stage,
                }
            )
    return PassportSubmissionResponse.model_validate(payload)


async def _response_from_submission(
    submission,
    *,
    session: AsyncSession,
) -> PassportSubmissionResponse:  # type: ignore[no-untyped-def]
    image_url = await MinioStorageRepository().get_presigned_url(submission.image_s3_key)
    payload = {
        **submission.__dict__,
        "status": submission.status.value,
        "image_url": image_url,
    }
    job = await PassportProcessingJobRepository(session).latest_for_submission(submission.id)
    if job:
        payload.update(
            {
                "processing_job_id": job.id,
                "processing_job_status": job.status.value,
                "processing_progress": job.progress,
                "processing_stage": job.current_stage,
            }
        )
    return PassportSubmissionResponse.model_validate(payload)


def _group_export_details(group) -> dict[str, str | None]:  # type: ignore[no-untyped-def]
    return {
        "name": group.name,
        "destination": group.destination,
        "travel_date": group.travel_date.isoformat() if group.travel_date else None,
        "return_date": group.return_date.isoformat() if group.return_date else None,
        "package_name": group.package_name,
    }


async def _export_group_details(
    session: AsyncSession,
    group_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, str | None]]:
    if not group_ids:
        return {}
    result = await session.execute(select(ClientGroupModel).where(ClientGroupModel.id.in_(set(group_ids))))
    return {group.id: _group_export_details(group) for group in result.scalars().all()}


async def _dispatch_processing_job(
    result: PassportSubmissionOutputDTO,
    *,
    session: AsyncSession,
    background_tasks: BackgroundTasks,
) -> None:
    if not result.processing_job_id:
        return

    # The worker uses a separate database session, so commit the queued rows
    # before dispatching to avoid a race with the worker reading the job.
    await session.commit()
    task_id = PassportProcessingDispatcher().dispatch(
        job_id=result.processing_job_id,
        submission_id=result.id,
        background_tasks=background_tasks,
    )
    if task_id:
        await PassportProcessingJobRepository(session).set_task_id(result.processing_job_id, task_id)
        await session.commit()


def _get_submit_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> SubmitPassportUseCase:
    return SubmitPassportUseCase(
        client_group_repo=ClientGroupRepository(session),
        passport_repo=PassportSubmissionRepository(session),
        storage_repo=MinioStorageRepository(),
        extraction_service=PassportExtractionService(),
        processing_job_repo=PassportProcessingJobRepository(session),
    )


def _get_list_passports_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ListPassportSubmissionsUseCase:
    return ListPassportSubmissionsUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_list_passport_groups_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ListPassportGroupSummariesUseCase:
    return ListPassportGroupSummariesUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_list_passports_by_group_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ListPassportSubmissionsByGroupUseCase:
    return ListPassportSubmissionsByGroupUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_get_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> GetPassportSubmissionUseCase:
    return GetPassportSubmissionUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_confirm_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ConfirmPassportSubmissionUseCase:
    return ConfirmPassportSubmissionUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_client_submit_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ClientSubmitPassportUseCase:
    return ClientSubmitPassportUseCase(
        passport_repo=PassportSubmissionRepository(session),
        client_group_repo=ClientGroupRepository(session),
        storage_repo=MinioStorageRepository(),
    )


def _get_reextract_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ReextractPassportSubmissionUseCase:
    return ReextractPassportSubmissionUseCase(
        passport_repo=PassportSubmissionRepository(session),
        storage_repo=MinioStorageRepository(),
        extraction_service=PassportExtractionService(),
        processing_job_repo=PassportProcessingJobRepository(session),
    )


def _get_retry_public_extraction_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RetryPublicPassportExtractionUseCase:
    return RetryPublicPassportExtractionUseCase(
        passport_repo=PassportSubmissionRepository(session),
        client_group_repo=ClientGroupRepository(session),
        storage_repo=MinioStorageRepository(),
        extraction_service=PassportExtractionService(),
    )


@router.post(
    "/upload/{token}",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a passport image using a secure token (Public)",
)
async def upload_passport(
    token: str,
    background_tasks: BackgroundTasks,
    client_name: str = Form(...),
    file: UploadFile = File(...),
    use_case: SubmitPassportUseCase = Depends(_get_submit_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    
    # 1. Read and validate file content using magic bytes + actual decoder.
    try:
        content = await file.read()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read file content",
        )
    validated = UploadValidator().validate(
        content=content,
        filename=file.filename,
        declared_content_type=file.content_type,
    )

    # 2. Execute use case
    try:
        result = await use_case.execute(
            token=token,
            file_content=validated.content,
            content_type=validated.content_type,
            filename=validated.filename,
            client_name=client_name,
        )
        await _dispatch_processing_job(result, session=session, background_tasks=background_tasks)
        return await _response_from_dto(result, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.get(
    "/upload/{token}/{submission_id}/status",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Poll passport extraction status for a public upload",
)
async def get_upload_passport_status(
    token: str,
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    group = await ClientGroupRepository(session).get_by_token(token)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload link was not found")

    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if not submission or submission.group_id != group.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passport submission was not found")

    return await _response_from_submission(submission, session=session)


@router.post(
    "/upload/{token}/{submission_id}/scan-again",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Rerun fallback MRZ extraction for a public upload",
)
async def scan_again_public_upload(
    token: str,
    submission_id: uuid.UUID,
    use_case: RetryPublicPassportExtractionUseCase = Depends(_get_retry_public_extraction_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        result = await use_case.execute(token=token, submission_id=submission_id)
        return await _response_from_dto(result, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.get(
    "/upload/{token}/{submission_id}/image",
    status_code=status.HTTP_200_OK,
    summary="Stream a public upload passport image through the API",
)
async def get_public_upload_passport_image(
    token: str,
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    group = await ClientGroupRepository(session).get_by_token(token)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload link was not found")

    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    if not submission or submission.group_id != group.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passport submission was not found")

    content = await MinioStorageRepository().get_file(submission.image_s3_key)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": 'inline; filename="passport.jpg"',
        },
    )


@router.delete(
    "/upload/{token}/{submission_id}",
    status_code=status.HTTP_200_OK,
    summary="Discard an unsubmitted public passport draft",
)
async def discard_public_upload(
    token: str,
    submission_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    group = await ClientGroupRepository(session).get_by_token(token)
    submission_repo = PassportSubmissionRepository(session)
    submission = await submission_repo.get_by_id(submission_id)
    if not group or not submission or submission.group_id != group.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passport draft was not found")
    if submission.status.value in {"client_submitted", "confirmed"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Submitted passports cannot be discarded")

    await MinioStorageRepository().delete_files(
        [key for key in (submission.image_s3_key, submission.thumbnail_s3_key) if key]
    )
    await submission_repo.delete(submission.id)
    return {"discarded": True}


@router.get(
    "/groups",
    response_model=list[PassportGroupSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List client groups that contain passport submissions",
)
async def list_passport_groups(
    current_user: User = Depends(get_current_active_user),
    use_case: ListPassportGroupSummariesUseCase = Depends(_get_list_passport_groups_use_case),
    skip: int = 0,
    limit: int = 50,
) -> list[PassportGroupSummaryResponse]:
    if not current_user.agency_id:
        return []

    result = await use_case.execute(
        agency_id=current_user.agency_id,
        skip=skip,
        limit=limit,
        created_by_user_id=_owner_scope_for(current_user),
    )
    return [PassportGroupSummaryResponse.model_validate(item) for item in result]


@router.get(
    "/groups/{group_id}",
    response_model=list[PassportSubmissionResponse],
    status_code=status.HTTP_200_OK,
    summary="List passport submissions within a client group",
)
async def list_passports_by_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    use_case: ListPassportSubmissionsByGroupUseCase = Depends(_get_list_passports_by_group_use_case),
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    include_deleted: bool = False,
) -> list[PassportSubmissionResponse]:
    if not current_user.agency_id:
        return []
    if include_deleted and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only super admins can view old data")

    result = await use_case.execute(
        agency_id=current_user.agency_id,
        group_id=group_id,
        skip=skip,
        limit=limit,
        search=search,
        created_by_user_id=None if include_deleted else _owner_scope_for(current_user),
        include_deleted_group=include_deleted,
    )
    return [PassportSubmissionResponse.model_validate(item) for item in result]


@router.get(
    "",
    response_model=list[PassportSubmissionResponse],
    status_code=status.HTTP_200_OK,
    summary="List passport submissions for the current agency",
)
async def list_passports(
    current_user: User = Depends(get_current_active_user),
    use_case: ListPassportSubmissionsUseCase = Depends(_get_list_passports_use_case),
    skip: int = 0,
    limit: int = 100,
    status_filter: str | None = None,
    search: str | None = None,
) -> list[PassportSubmissionResponse]:
    if not current_user.agency_id:
        return []

    result = await use_case.execute(
        agency_id=current_user.agency_id,
        skip=skip,
        limit=limit,
        status_filter=status_filter,
        search=search,
        created_by_user_id=_owner_scope_for(current_user),
    )
    return [PassportSubmissionResponse.model_validate(item) for item in result]


@router.get(
    "/groups/{group_id}/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export a client group's passport submissions to Excel",
)
async def export_passports_by_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    group_repo = ClientGroupRepository(session)
    group = await group_repo.get_by_id(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found")
    if not current_user.can_access_agency(group.agency_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this group")
    if current_user.role == UserRole.AGENCY_STAFF and not await group_repo.manager_can_access(group_id, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this manager's group")

    passport_repo = PassportSubmissionRepository(session)
    submissions = await passport_repo.list_by_group(
        current_user.agency_id,
        group_id,
        limit=5000,
        exclude_archived_groups=True,
        created_by_user_id=_owner_scope_for(current_user),
    )
    content = PassportExcelExporter().export_group(
        submissions,
        group_name=group.name,
        group_details={group.id: _group_export_details(group)},
    )

    await AuditLogRepository(session).record(
        action="passport_group_exported",
        entity_type="client_group",
        entity_id=str(group_id),
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={"submission_count": len(submissions)},
    )

    filename = f"passport-export-{group_id}.xlsx"
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export selected passport submissions to Excel",
)
async def export_selected_passports(
    body: ExportSelectedPassportsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    stmt = (
        select(PassportSubmissionModel)
        .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        .where(
            PassportSubmissionModel.id.in_(body.submission_ids),
            PassportSubmissionModel.status.in_(_submitted_statuses()),
        )
    )
    if current_user.role != UserRole.SUPER_ADMIN:
        stmt = stmt.where(PassportSubmissionModel.agency_id == current_user.agency_id)
    stmt = _apply_manager_visibility(stmt, current_user)
    result = await session.execute(stmt)
    submissions = [PassportSubmissionRepository._to_entity(model) for model in result.scalars().all()]
    if not submissions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No exportable passport submissions found")

    content = PassportExcelExporter().export_group(
        submissions,
        group_name="Selected Passports",
        group_details=await _export_group_details(session, [submission.group_id for submission in submissions]),
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="selected-passports.xlsx"'},
    )


@router.post(
    "/groups/export.xlsx",
    status_code=status.HTTP_200_OK,
    summary="Export selected passport groups to Excel",
)
async def export_selected_groups(
    body: ExportSelectedGroupsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    stmt = (
        select(PassportSubmissionModel)
        .join(ClientGroupModel, PassportSubmissionModel.group_id == ClientGroupModel.id)
        .where(
            PassportSubmissionModel.group_id.in_(body.group_ids),
            PassportSubmissionModel.status.in_(_submitted_statuses()),
        )
    )
    if current_user.role != UserRole.SUPER_ADMIN:
        stmt = stmt.where(PassportSubmissionModel.agency_id == current_user.agency_id)
    stmt = _apply_manager_visibility(stmt, current_user)
    result = await session.execute(stmt)
    submissions = [PassportSubmissionRepository._to_entity(model) for model in result.scalars().all()]
    if not submissions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No exportable passport submissions found")

    content = PassportExcelExporter().export_group(
        submissions,
        group_name="Selected Groups",
        group_details=await _export_group_details(session, body.group_ids),
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="selected-groups-passports.xlsx"'},
    )


@router.get(
    "/{submission_id}",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a passport submission by id",
)
async def get_passport(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        result = await use_case.execute(submission_id)
        if not current_user.can_access_agency(result.agency_id):
            raise AuthorizationError("You do not have access to this passport submission")
        await _ensure_group_owner_scope(result.group_id, current_user, ClientGroupRepository(session))

        image_url = await MinioStorageRepository().get_presigned_url(result.image_s3_key)
        return PassportSubmissionResponse.model_validate({**result.__dict__, "image_url": image_url})
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)


@router.post(
    "/{submission_id}/client-submit",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit client-reviewed passport fields (Public)",
)
async def client_submit_passport(
    submission_id: uuid.UUID,
    body: ClientSubmitPassportRequest,
    use_case: ClientSubmitPassportUseCase = Depends(_get_client_submit_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        result = await use_case.execute(
            submission_id,
            group_token=body.group_token,
            confirmed_fields=body.confirmed_fields,
            client_email=str(body.client_email),
            client_phone=body.client_phone,
        )
        await AuditLogRepository(session).record(
            action="client_passport_submitted",
            entity_type="passport_submission",
            entity_id=str(result.id),
            agency_id=result.agency_id,
            actor_email=str(body.client_email),
            metadata={"group_id": str(result.group_id), "client_phone": body.client_phone},
        )
        await NotificationRepository(session).create(
            agency_id=result.agency_id,
            type="passport_submitted",
            title="Client passport submitted",
            message=f"{result.client_name} submitted reviewed passport details.",
            entity_type="passport_submission",
            entity_id=str(result.id),
        )
        return PassportSubmissionResponse.model_validate(result)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.post(
    "/{submission_id}/reextract",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Rerun automatic extraction for a passport submission",
)
async def reextract_passport(
    submission_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    reextract_use_case: ReextractPassportSubmissionUseCase = Depends(_get_reextract_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        if not current_user.can_access_agency(existing.agency_id):
            raise AuthorizationError("You do not have access to this passport submission")
        await _ensure_group_owner_scope(existing.group_id, current_user, ClientGroupRepository(session))

        result = await reextract_use_case.execute(submission_id)
        await _dispatch_processing_job(result, session=session, background_tasks=background_tasks)
        await AuditLogRepository(session).record(
            action="passport_reextract_queued",
            entity_type="passport_submission",
            entity_id=str(result.id),
            agency_id=result.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
        )
        return await _response_from_dto(result, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.post(
    "/{submission_id}/cancel-processing",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Request cancellation of queued passport extraction",
)
async def cancel_passport_processing(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        if not current_user.can_access_agency(existing.agency_id):
            raise AuthorizationError("You do not have access to this passport submission")
        await _ensure_group_owner_scope(existing.group_id, current_user, ClientGroupRepository(session))

        job_repo = PassportProcessingJobRepository(session)
        job = await job_repo.latest_for_submission(submission_id)
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Processing job was not found")

        await job_repo.request_cancel(job.id)
        await AuditLogRepository(session).record(
            action="passport_processing_cancel_requested",
            entity_type="passport_submission",
            entity_id=str(submission_id),
            agency_id=existing.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={"job_id": str(job.id)},
        )
        submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)
        return await _response_from_submission(submission, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)


@router.post(
    "/{submission_id}/confirm",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm reviewed passport fields",
)
async def confirm_passport(
    submission_id: uuid.UUID,
    body: ConfirmPassportSubmissionRequest,
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    confirm_use_case: ConfirmPassportSubmissionUseCase = Depends(_get_confirm_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        if not current_user.can_access_agency(existing.agency_id):
            raise AuthorizationError("You do not have access to this passport submission")
        await _ensure_group_owner_scope(existing.group_id, current_user, ClientGroupRepository(session))

        result = await confirm_use_case.execute(
            submission_id,
            confirmed_fields=body.confirmed_fields,
        )
        await AuditLogRepository(session).record(
            action="passport_confirmed",
            entity_type="passport_submission",
            entity_id=str(result.id),
            agency_id=result.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
        )
        image_url = await MinioStorageRepository().get_presigned_url(result.image_s3_key)
        return PassportSubmissionResponse.model_validate({**result.__dict__, "image_url": image_url})
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
