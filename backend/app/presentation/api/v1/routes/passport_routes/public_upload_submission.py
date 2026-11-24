"""Public passport submission: focused capability and workflow owner."""

from __future__ import annotations

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.public_upload_capability import public_upload_is_active
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.core.security.upload_session import upload_session_matches_identifier
from app.domain.exceptions.exceptions import EntityNotFoundError, PassDetectionError, StorageError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportSubmissionResponse,
)

from .dependencies import (
    _get_submit_passport_use_case,
)
from .public_processing_support import dispatch_public_extraction
from .public_security import _validated_upload_file
from .public_upload_documents import validate_public_upload_documents
from .public_upload_scope import logger
from .response_support import _response_from_dto

router = APIRouter()


@router.post(
    "/upload/{token}",
    response_model=PassportSubmissionResponse,
    response_model_exclude={"document_follow_up", "display_name"},
    status_code=status.HTTP_201_CREATED,
    summary="Submit a passport image using a secure token (Public)",
)
async def upload_passport(
    token: str,
    background_tasks: BackgroundTasks,
    client_name: str = Form(...),
    acquisition_mode: str = Form(..., pattern="^(camera|file)$"),
    upload_idempotency_key: str = Form(..., min_length=32, max_length=128),
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=32,
        max_length=128,
    ),
    qualifier_selection_token: str | None = Form(
        default=None,
        min_length=32,
        max_length=256,
    ),
    file: UploadFile | None = File(None, description="Passport personal details page"),
    passport_back_file: UploadFile | None = File(None, description="Passport address details page"),
    passport_photo_file: UploadFile | None = File(
        None,
        description="Optional original Visa Photo captured against a verified plain light background",
    ),
    passport_cover_file: UploadFile | None = File(None, description="Passport front cover"),
    passport_back_cover_file: UploadFile | None = File(None, description="Passport back cover"),
    visa_photo_source: str | None = Form(None, pattern="^(camera|file)$"),
    use_case: SubmitPassportUseCase = Depends(_get_submit_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    if not upload_session_matches_identifier(
        upload_session_id,
        upload_idempotency_key,
    ):
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "domain_rejected",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload session identifier does not match this upload attempt.",
        )

    # Reject revoked or unknown public capabilities before any image decoder.
    group = await ClientGroupRepository(session).get_by_token(token)
    if group is None or not public_upload_is_active(group):
        raise HTTPException(status_code=404, detail="Upload link was not found")

    document_arguments = await validate_public_upload_documents(
        group=group,
        acquisition_mode=acquisition_mode,
        visa_photo_source=visa_photo_source,
        file=file,
        passport_back_file=passport_back_file,
        passport_photo_file=passport_photo_file,
        passport_cover_file=passport_cover_file,
        passport_back_cover_file=passport_back_cover_file,
        validator=_validated_upload_file,
    )

    # 2. Execute use case
    failure_metric_recorded = False
    try:
        result = await use_case.execute(
            token=token,
            **document_arguments,
            client_name=client_name,
            acquisition_mode=acquisition_mode,
            upload_idempotency_key=upload_idempotency_key,
            qualifier_selection_token=qualifier_selection_token,
        )
        if not result.idempotent_replay:
            await propagate_mobile_passenger_change(
                session,
                agency_id=result.agency_id,
                group_id=result.group_id,
                passenger_submission_ids=[result.id],
                actor_user_id=None,
                change_kind="documents",
            )
        try:
            if result.processing_job_id:
                result = await dispatch_public_extraction(
                    result,
                    session=session,
                    background_tasks=background_tasks,
                )
            else:
                # A details-only draft has no processing outbox. Persist it
                # explicitly before returning the capability to the browser.
                await session.commit()
        except Exception as exc:
            await session.rollback()
            # A database commit exception is ambiguous: the server may have
            # committed before the connection failed, and this may also be an
            # idempotent replay of existing objects. Never delete durable image
            # keys here, because that could leave a committed row dangling.
            logger.error(
                "passport_upload_database_commit_failed",
                group_id=str(result.group_id),
                error_type=type(exc).__name__,
            )
            record_operational_event(
                OperationalEvent.UPLOAD_RESULT,
                "database_failed",
            )
            failure_metric_recorded = True
            raise StorageError(
                "Passport images could not be saved. Please try the upload again."
            ) from exc
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            ("idempotent_replay" if result.idempotent_replay else "success"),
        )
        return await _response_from_dto(
            result,
            session=session,
            include_document_urls=False,
        )
    except EntityNotFoundError as e:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "domain_rejected",
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except StorageError as e:
        if not failure_metric_recorded:
            record_operational_event(
                OperationalEvent.UPLOAD_RESULT,
                "storage_failed",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=e.message,
        )
    except PassDetectionError as e:
        record_operational_event(
            OperationalEvent.UPLOAD_RESULT,
            "domain_rejected",
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)
    except Exception:
        if not failure_metric_recorded:
            record_operational_event(
                OperationalEvent.UPLOAD_RESULT,
                "unexpected_failure",
            )
        raise


upload_passport.__module__ = "app.presentation.api.v1.routes.passport_routes.public_upload"
