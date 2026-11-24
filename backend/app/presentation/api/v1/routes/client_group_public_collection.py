"""Public Collection for upload links; HTTP declarations remain in client_groups."""

from __future__ import annotations

from fastapi import HTTPException, Response, status

from app.application.use_cases.client_groups.create_qualifier_selection_use_case import (
    CreateQualifierSelectionUseCase,
)
from app.application.use_cases.client_groups.get_client_group_by_token_use_case import (
    GetClientGroupByTokenUseCase,
)
from app.application.use_cases.client_groups.get_qualifier_selection_use_case import (
    GetQualifierSelectionUseCase,
)
from app.core.security.upload_session import is_valid_upload_session_id
from app.domain.exceptions.exceptions import (
    EntityNotFoundError,
    PassDetectionError,
)
from app.infrastructure.observability.operational_events import (
    is_allowed_operational_reason,
    parse_public_operational_event,
)
from app.presentation.api.v1.routes.client_group_operation_dependencies import (
    RecordOperationalEvent,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    ClientGroupResponse,
    CreateQualifierSelectionRequest,
    CreateQualifierSelectionResponse,
    PublicFlowTelemetryRequest,
    QualifierSelectionStateResponse,
)


async def get_client_group_by_token(
    token: str, use_case: GetClientGroupByTokenUseCase
) -> ClientGroupResponse:
    try:
        result = await use_case.execute(token=token)
        return ClientGroupResponse.model_validate(result)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except PassDetectionError as e:
        if e.code == "CLIENT_GROUP_CLOSED":
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={"code": e.code, "message": e.message},
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


async def record_public_flow_telemetry(
    token: str,
    body: PublicFlowTelemetryRequest,
    upload_session_id: str,
    use_case: GetClientGroupByTokenUseCase,
    *,
    record_operational_event: RecordOperationalEvent,
) -> Response:
    """Accept only fixed, PII-free events for an active upload link."""

    if not is_valid_upload_session_id(upload_session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload session identifier is invalid.",
        )
    event = parse_public_operational_event(body.event)
    if event is None or not is_allowed_operational_reason(
        event,
        body.reason,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported upload telemetry event.",
        )

    try:
        await use_case.execute(token=token)
    except (EntityNotFoundError, PassDetectionError):
        # Match the upload reconciliation privacy contract: invalid, closed,
        # and expired bearer links do not become a telemetry oracle.
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={"Cache-Control": "private, no-store"},
        )

    record_operational_event(event, body.reason)
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Cache-Control": "private, no-store"},
    )


async def create_qualifier_selection(
    token: str, request: CreateQualifierSelectionRequest, use_case: CreateQualifierSelectionUseCase
) -> CreateQualifierSelectionResponse:
    try:
        result = await use_case.execute(
            group_token=token,
            is_self=request.is_self,
            relation_code=request.relation_code,
            other_relation=request.other_relation,
        )
        return CreateQualifierSelectionResponse.model_validate(result)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        )
    except PassDetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        )


async def get_qualifier_selection(
    token: str, qualifier_selection_token: str, use_case: GetQualifierSelectionUseCase
) -> QualifierSelectionStateResponse:
    try:
        result = await use_case.execute(
            group_token=token,
            selection_token=qualifier_selection_token,
        )
        return QualifierSelectionStateResponse.model_validate(result)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        )
    except PassDetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        )
