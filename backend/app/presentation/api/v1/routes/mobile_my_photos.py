"""Passenger-only, trip-scoped My Photos API."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.errors import MyPhotosRateLimited, MyPhotosUnavailable
from app.application.my_photos.providers import DeliveryResolution
from app.application.my_photos.states import MatchFilter
from app.application.security.mobile_access_policy import AuthorizedMobileTrip, MobileAccessPolicy
from app.core.logging.logger import get_logger
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.my_photos_models import MyPhotoGalleryModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.my_photos.dispatcher import enqueue_media_job, enqueue_search_job
from app.infrastructure.my_photos.service import MyPhotosService
from app.infrastructure.my_photos.telemetry import my_photos_metrics
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosConsentRequest,
    MyPhotosDeleteEnrollmentRequest,
    MyPhotosDeleteEnrollmentResponse,
    MyPhotosDownloadAuthorizationRequest,
    MyPhotosDownloadAuthorizationResponse,
    MyPhotosDownloadPlanResponse,
    MyPhotosFeedbackRequest,
    MyPhotosFeedbackResponse,
    MyPhotosLivenessCompleteRequest,
    MyPhotosLivenessCompleteResponse,
    MyPhotosLivenessSessionResponse,
    MyPhotosLivenessStartRequest,
    MyPhotosPhotoPageResponse,
    MyPhotosPrepareRequest,
    MyPhotosPrepareResponse,
    MyPhotosSearchResponse,
    MyPhotosSummaryResponse,
)
from app.presentation.dependencies.mobile_auth import require_unrestricted_mobile_claims

router = APIRouter()
logger = get_logger(__name__)
_SINGLE_RANGE = re.compile(r"^bytes=(\d{0,19})-(\d{0,19})$")


@dataclass(frozen=True, slots=True)
class _AuthorizedRequest:
    claims: MobileAccessClaims
    trip: AuthorizedMobileTrip


def _dispatch_committed_job(
    *,
    kind: Literal["search", "media"],
    job_id: uuid.UUID,
    dispatch: Callable[[uuid.UUID], None],
) -> None:
    """Publish best-effort without turning a committed acceptance into 500."""

    try:
        dispatch(job_id)
    except Exception as exc:
        my_photos_metrics.dispatch("recovery_pending")
        logger.warning(
            "my_photos_dispatch_deferred_to_recovery",
            job_kind=kind,
            error_type=type(exc).__name__,
        )
    else:
        my_photos_metrics.dispatch("published")


async def _authorize(
    *,
    group_id: uuid.UUID,
    claims: MobileAccessClaims,
    session: AsyncSession,
    allow_disabled_feature: bool = False,
) -> _AuthorizedRequest:
    try:
        trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)
        if claims.principal_type != "passenger" or trip.passenger_identity is None:
            raise AuthorizationError("My Photos is available only to the signed-in passenger")
    except AuthorizationError:
        my_photos_metrics.authorization(allowed=False)
        raise
    my_photos_metrics.authorization(allowed=True)
    if not allow_disabled_feature:
        feature_enabled = await session.scalar(
            select(MyPhotoGalleryModel.feature_enabled)
            .where(
                MyPhotoGalleryModel.agency_id == claims.agency_id,
                MyPhotoGalleryModel.group_id == group_id,
                MyPhotoGalleryModel.gc_group_access_id == trip.access.id,
            )
            .limit(1)
        )
        if feature_enabled is not True:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_FEATURE_UNAVAILABLE",
                "My Photos is not available for this trip.",
            )
    return _AuthorizedRequest(claims=claims, trip=trip)


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"


def _rate_limited_response(exc: MyPhotosRateLimited) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error": {"code": exc.code, "message": exc.message}},
        headers={
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "Retry-After": str(exc.retry_after_seconds),
        },
    )


@router.get("/trips/{group_id}/my-photos", response_model=MyPhotosSummaryResponse)
async def get_my_photos_summary(
    group_id: uuid.UUID,
    response: Response,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MyPhotosSummaryResponse:
    authorized = await _authorize(
        group_id=group_id,
        claims=claims,
        session=session,
        allow_disabled_feature=True,
    )
    _private(response)
    with my_photos_metrics.api_timer("summary"):
        return await MyPhotosService(session).summary(claims=claims, trip=authorized.trip)


@router.post("/trips/{group_id}/my-photos/consent", response_model=MyPhotosSummaryResponse)
async def accept_my_photos_consent(
    group_id: uuid.UUID,
    request: MyPhotosConsentRequest,
    response: Response,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MyPhotosSummaryResponse:
    authorized = await _authorize(group_id=group_id, claims=claims, session=session)
    _private(response)
    return await MyPhotosService(session).accept_consent(
        claims=claims, trip=authorized.trip, request=request
    )


@router.post(
    "/trips/{group_id}/my-photos/liveness-sessions",
    response_model=MyPhotosLivenessSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_my_photos_liveness(
    group_id: uuid.UUID,
    request: MyPhotosLivenessStartRequest,
    response: Response,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MyPhotosLivenessSessionResponse | Response:
    authorized = await _authorize(group_id=group_id, claims=claims, session=session)
    _private(response)
    try:
        return await MyPhotosService(session).start_liveness(
            claims=claims, trip=authorized.trip, request=request
        )
    except MyPhotosRateLimited as exc:
        return _rate_limited_response(exc)


@router.post(
    "/trips/{group_id}/my-photos/liveness-sessions/{session_id}/complete",
    response_model=MyPhotosLivenessCompleteResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def complete_my_photos_liveness(
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    request: MyPhotosLivenessCompleteRequest,
    response: Response,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MyPhotosLivenessCompleteResponse | Response:
    authorized = await _authorize(group_id=group_id, claims=claims, session=session)
    _private(response)
    try:
        result = await MyPhotosService(session).complete_liveness(
            claims=claims,
            trip=authorized.trip,
            session_id=session_id,
            request=request,
        )
    except MyPhotosRateLimited as exc:
        return _rate_limited_response(exc)
    if result.search_run_id is not None:
        # The worker must never race the request transaction that created its
        # durable job row. Development uses the same queue and worker contract.
        await session.commit()
        _dispatch_committed_job(
            kind="search",
            job_id=result.search_run_id,
            dispatch=enqueue_search_job,
        )
    return result


@router.get("/trips/{group_id}/my-photos/search", response_model=MyPhotosSearchResponse)
async def get_my_photos_search(
    group_id: uuid.UUID,
    response: Response,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MyPhotosSearchResponse:
    authorized = await _authorize(group_id=group_id, claims=claims, session=session)
    _private(response)
    return await MyPhotosService(session).search_status(claims=claims, trip=authorized.trip)


@router.get("/trips/{group_id}/my-photos/photos", response_model=MyPhotosPhotoPageResponse)
async def get_my_photos_page(
    group_id: uuid.UUID,
    response: Response,
    match_filter: MatchFilter = Query(default="best", alias="filter"),
    cursor: str | None = Query(default=None, min_length=16, max_length=768),
    limit: int = Query(default=48, ge=1, le=60),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MyPhotosPhotoPageResponse:
    authorized = await _authorize(group_id=group_id, claims=claims, session=session)
    _private(response)
    with my_photos_metrics.api_timer("page"):
        return await MyPhotosService(session).photo_page(
            claims=claims,
            trip=authorized.trip,
            match_filter=match_filter,
            cursor=cursor,
            limit=limit,
        )


@router.put(
    "/trips/{group_id}/my-photos/photos/{asset_id}/feedback",
    response_model=MyPhotosFeedbackResponse,
)
async def put_my_photos_feedback(
    group_id: uuid.UUID,
    asset_id: uuid.UUID,
    request: MyPhotosFeedbackRequest,
    response: Response,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MyPhotosFeedbackResponse:
    authorized = await _authorize(group_id=group_id, claims=claims, session=session)
    _private(response)
    return await MyPhotosService(session).record_feedback(
        claims=claims,
        trip=authorized.trip,
        asset_id=asset_id,
        request=request,
    )


@router.delete(
    "/trips/{group_id}/my-photos/enrollment",
    response_model=MyPhotosDeleteEnrollmentResponse,
)
async def delete_my_photos_enrollment(
    group_id: uuid.UUID,
    response: Response,
    request: MyPhotosDeleteEnrollmentRequest = Body(...),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MyPhotosDeleteEnrollmentResponse:
    authorized = await _authorize(group_id=group_id, claims=claims, session=session)
    _private(response)
    return await MyPhotosService(session).delete_enrollment(
        claims=claims, trip=authorized.trip, request=request
    )


@router.post(
    "/trips/{group_id}/my-photos/photos/{asset_id}/prepare",
    response_model=MyPhotosPrepareResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def prepare_my_photos_media(
    group_id: uuid.UUID,
    asset_id: uuid.UUID,
    request: MyPhotosPrepareRequest,
    response: Response,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MyPhotosPrepareResponse:
    authorized = await _authorize(group_id=group_id, claims=claims, session=session)
    _private(response)
    result = await MyPhotosService(session).prepare_media(
        claims=claims, trip=authorized.trip, asset_id=asset_id, request=request
    )
    if result.preparation_id is not None:
        await session.commit()
        _dispatch_committed_job(
            kind="media",
            job_id=result.preparation_id,
            dispatch=enqueue_media_job,
        )
    return result


@router.post(
    "/trips/{group_id}/my-photos/download-authorizations",
    response_model=MyPhotosDownloadAuthorizationResponse,
)
async def authorize_my_photos_downloads(
    group_id: uuid.UUID,
    request: MyPhotosDownloadAuthorizationRequest,
    response: Response,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MyPhotosDownloadAuthorizationResponse:
    authorized = await _authorize(group_id=group_id, claims=claims, session=session)
    _private(response)
    with my_photos_metrics.api_timer("download_authorization"):
        return await MyPhotosService(session).authorize_downloads(
            claims=claims, trip=authorized.trip, request=request
        )


@router.get(
    "/trips/{group_id}/my-photos/download-plan",
    response_model=MyPhotosDownloadPlanResponse,
)
async def get_my_photos_download_plan(
    group_id: uuid.UUID,
    response: Response,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MyPhotosDownloadPlanResponse:
    authorized = await _authorize(group_id=group_id, claims=claims, session=session)
    _private(response)
    return await MyPhotosService(session).download_plan(claims=claims, trip=authorized.trip)


@router.get(
    "/trips/{group_id}/my-photos/photos/{asset_id}/content/{variant}",
    response_class=Response,
)
async def get_my_photos_photo_content(
    group_id: uuid.UUID,
    asset_id: uuid.UUID,
    variant: Literal["thumbnail", "preview"],
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    authorized = await _authorize(group_id=group_id, claims=claims, session=session)
    delivery = await MyPhotosService(session).preview_content_or_location(
        claims=claims,
        trip=authorized.trip,
        asset_id=asset_id,
        variant=variant,
    )
    if isinstance(delivery, DeliveryResolution):
        return RedirectResponse(
            url=delivery.location,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={
                "Cache-Control": "private, no-store",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
                "X-GC-Media-Expires-At": _utc_iso(delivery.expires_at),
                "X-Content-Type-Options": "nosniff",
            },
        )
    content, checksum = delivery
    return _photo_preview_bytes_response(
        content=content,
        checksum=checksum,
        asset_id=asset_id,
        variant=variant,
    )


def _photo_preview_bytes_response(
    *,
    content: bytes,
    checksum: str,
    asset_id: uuid.UUID,
    variant: Literal["thumbnail", "preview"],
) -> Response:
    return Response(
        content=content,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            "Pragma": "no-cache",
            "Vary": "Authorization",
            "Content-Disposition": (
                f'inline; filename="my-photo-{asset_id}-{variant}{_image_extension("image/png")}"'
            ),
            "X-Content-SHA256": checksum,
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/trips/{group_id}/my-photos/download-authorizations/{authorization_id}/content",
    response_class=Response,
)
async def get_my_photos_download(
    group_id: uuid.UUID,
    authorization_id: uuid.UUID,
    range_header: str | None = Header(default=None, alias="Range"),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    authorized = await _authorize(group_id=group_id, claims=claims, session=session)
    delivery = await MyPhotosService(session).download_content_or_location(
        claims=claims,
        trip=authorized.trip,
        authorization_id=authorization_id,
    )
    if isinstance(delivery, DeliveryResolution):
        # A 307 preserves the GET and Range header. The signed location is
        # created only after passenger/group authorization, never stored in
        # PostgreSQL, and expires no later than the opaque authorization.
        return RedirectResponse(
            url=delivery.location,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={
                "Cache-Control": "private, no-store",
                "Pragma": "no-cache",
                "Referrer-Policy": "no-referrer",
                "X-GC-Media-Expires-At": _utc_iso(delivery.expires_at),
                "X-Content-Type-Options": "nosniff",
            },
        )
    content, content_type, checksum = delivery
    start, end, partial = _resolve_range(range_header, len(content))
    if start is None or end is None:
        return Response(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{len(content)}", "Cache-Control": "no-store"},
        )
    body = content[start : end + 1]
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store",
        "Pragma": "no-cache",
        "Content-Length": str(len(body)),
        "Content-Disposition": (
            f'attachment; filename="my-photo-{authorization_id}{_image_extension(content_type)}"'
        ),
        "X-Content-SHA256": checksum,
        "X-Content-Type-Options": "nosniff",
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{len(content)}"
    return Response(
        content=body,
        media_type=content_type,
        status_code=status.HTTP_206_PARTIAL_CONTENT if partial else status.HTTP_200_OK,
        headers=headers,
    )


def _image_extension(content_type: str) -> str:
    extensions = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    try:
        return extensions[content_type]
    except KeyError as exc:
        raise ValueError("Unsupported My Photos content type") from exc


def _resolve_range(value: str | None, total: int) -> tuple[int | None, int | None, bool]:
    if value is None:
        return 0, total - 1, False
    match = _SINGLE_RANGE.fullmatch(value)
    if match is None or "," in value:
        return None, None, False
    first, last = match.groups()
    if not first and not last:
        return None, None, False
    if first:
        start = int(first)
        end = int(last) if last else total - 1
        if start >= total or end < start:
            return None, None, False
        return start, min(end, total - 1), True
    suffix = int(last)
    if suffix <= 0:
        return None, None, False
    return max(total - suffix, 0), total - 1, True


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
