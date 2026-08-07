"""Compact, read-only resources for the native Group Companion application.

Every trip-scoped handler evaluates the shared mobile access policy before it
queries content.  The projections deliberately omit storage keys, raw object
URLs, passport fields, internal notes, and staff-only workflow metadata.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import uuid
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.mobile.coordinator_roster_revision import (
    coordinator_roster_revision,
)
from app.application.security.mobile_access_policy import (
    AuthorizedMobileTrip,
    MobileAccessPolicy,
)
from app.core.config.settings import get_settings
from app.core.security.mobile_jwt import (
    MobileAccessClaims,
    create_mobile_document_grant,
    decode_mobile_document_grant,
    hash_mobile_lookup,
    validate_mobile_document_grant,
)
from app.domain.entities.entities import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
    GroupStatus,
)
from app.domain.exceptions.exceptions import (
    AuthenticationError,
    AuthorizationError,
    EntityNotFoundError,
)
from app.domain.value_objects.travel_document_taxonomy import (
    FLIGHT_TICKET_DOCUMENT_TYPES,
    MOBILE_PERSONAL_DOCUMENT_TYPES,
    document_lane,
    mobile_document_category,
)
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCAnnouncementModel,
    GCCommonDocumentModel,
    GCGroupAccessModel,
    GCItineraryDayModel,
    GCItineraryItemModel,
    GCItineraryVersionModel,
    MobileDeviceSessionModel,
    MobileDocumentMetadataCacheModel,
    MobilePassengerIdentityModel,
    MobilePassengerSessionIdentityModel,
    MobileSyncChangeModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    DistributedDocumentModel,
    DocumentWhatsAppDeliveryModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingHotelModel,
    RoomingRoomModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.qr.approved_passenger_qr_issuer import ensure_mobile_passenger_qr
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileAnnouncementPageResponse,
    MobileAnnouncementResponse,
    MobileCommonDocumentPageResponse,
    MobileCommonDocumentResponse,
    MobileDocumentAuthorizationResponse,
    MobileItineraryDayResponse,
    MobileItineraryItemResponse,
    MobileItineraryResponse,
    MobileManagerReadinessResponse,
    MobileManifestResources,
    MobileManifestResponse,
    MobileManifestVersions,
    MobileMealResponse,
    MobilePersonalDocumentPageResponse,
    MobilePersonalDocumentResponse,
    MobilePrincipalResponse,
    MobileQRResponse,
    MobileRoomResponse,
    MobileSyncAcknowledgementRequest,
    MobileSyncAcknowledgementResponse,
    MobileSyncChangeResponse,
    MobileSyncPageResponse,
    MobileTripsResponse,
    MobileTripSummaryResponse,
)
from app.presentation.dependencies.mobile_auth import (
    get_current_mobile_claims,
    require_unrestricted_mobile_claims,
)
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()

_MAX_TRIP_PAGE = 100
_MAX_ANNOUNCEMENT_PAGE = 200
_MAX_DOCUMENT_PAGE = 200
_MAX_SYNC_PAGE = 500
_MAX_PERSONAL_DOCUMENTS = 200
_MOBILE_DOCUMENT_STREAM_SLOTS = asyncio.Semaphore(8)
_MOBILE_RELEASED_DOCUMENT_DELIVERY_STATUSES = ("submitted", "sent", "delivered", "read")
_ROOM_NAMESPACE = uuid.UUID("d41f0d72-5c68-4182-b4b7-fc8d6ae87386")
_MEAL_NAMESPACE = uuid.UUID("14e1d943-dd99-4309-adf3-242bcc49324a")
_PASSPORT_FRONT_NAMESPACE = uuid.UUID("5e9d0cef-b0f0-4e32-809f-941a443ec85d")
_PASSPORT_BACK_NAMESPACE = uuid.UUID("c90c7b7a-d8bb-4eac-881b-27f10d8b242b")
_ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
}


@dataclass(frozen=True, slots=True)
class _MobileDocumentSource:
    document_id: uuid.UUID
    scope: str
    category: str
    display_name: str
    safe_filename: str
    content_type: str
    storage_key: str
    source_kind: str
    source_id: uuid.UUID
    source_updated_at: datetime
    passenger_identity_id: uuid.UUID | None
    passenger_submission_id: uuid.UUID | None
    common_document: GCCommonDocumentModel | None = None


@dataclass(frozen=True, slots=True)
class _MobileDocumentStreamPlan:
    """Immutable, fully authorized object stream contract.

    The plan contains no ORM instances and is created before the request
    session is released. Streaming can therefore wait for admission or run for
    a slow client without retaining a database transaction or connection.
    """

    storage_key: str
    safe_filename: str
    content_type: str
    expected_size: int
    expected_checksum: str
    response_start: int
    is_partial: bool


@router.get("/me", response_model=MobilePrincipalResponse)
async def get_mobile_me(
    claims: MobileAccessClaims = Depends(get_current_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobilePrincipalResponse:
    """Top-level alias retained independently of the authentication namespace."""

    if claims.principal_type == "passenger":
        principal = (
            await session.execute(
                select(
                    PassportSubmissionModel.client_name,
                    PassportSubmissionModel.client_email,
                    MobilePassengerIdentityModel.normalized_phone_number,
                    MobilePassengerIdentityModel.passenger_submission_id,
                )
                .join(
                    MobilePassengerIdentityModel,
                    MobilePassengerIdentityModel.passenger_submission_id
                    == PassportSubmissionModel.id,
                )
                .where(
                    MobilePassengerIdentityModel.id == claims.principal_id,
                    MobilePassengerIdentityModel.agency_id == claims.agency_id,
                    PassportSubmissionModel.agency_id == claims.agency_id,
                )
                .limit(1)
            )
        ).first()
    else:
        user = (
            await session.execute(
                select(UserModel.full_name, UserModel.email).where(
                    UserModel.id == claims.principal_id,
                    UserModel.agency_id == claims.agency_id,
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                )
            )
        ).first()
        if user is None:
            principal = None
        else:
            phone_number = None
            if claims.principal_type == "client_manager":
                phone_number = (
                    await session.execute(
                        select(ClientManagerProfileModel.normalized_phone_number).where(
                            ClientManagerProfileModel.user_id == claims.principal_id,
                            ClientManagerProfileModel.agency_id == claims.agency_id,
                            ClientManagerProfileModel.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
            principal = (user[0], user[1], phone_number, None)
    if principal is None or not principal[0]:
        raise AuthenticationError("Mobile account is inactive")
    return MobilePrincipalResponse(
        id=claims.principal_id,
        account_id=claims.account_id,
        principal_type=claims.principal_type,
        agency_id=claims.agency_id,
        passenger_id=principal[3],
        display_name=str(principal[0]),
        email=str(principal[1]) if principal[1] else None,
        phone_number=str(principal[2]) if principal[2] else None,
        force_password_change=False,
    )


@router.get("/trips", response_model=MobileTripsResponse)
async def list_mobile_trips(
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=_MAX_TRIP_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileTripsResponse:
    """Return only explicitly granted, currently available groups."""

    now = datetime.now(tz=UTC)
    statement = (
        select(GCGroupAccessModel, ClientGroupModel)
        .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
        .where(
            GCGroupAccessModel.agency_id == claims.agency_id,
            ClientGroupModel.agency_id == claims.agency_id,
            ClientGroupModel.status.in_((GroupStatus.ACTIVE.value, GroupStatus.CLOSED.value)),
            ClientGroupModel.deleted_at.is_(None),
            GCGroupAccessModel.is_enabled.is_(True),
            GCGroupAccessModel.revoked_at.is_(None),
            or_(
                GCGroupAccessModel.access_starts_at.is_(None),
                GCGroupAccessModel.access_starts_at <= now,
            ),
            or_(
                GCGroupAccessModel.access_expires_at.is_(None),
                GCGroupAccessModel.access_expires_at > now,
            ),
        )
    )

    if claims.principal_type == "passenger":
        statement = (
            statement.add_columns(
                MobilePassengerSessionIdentityModel.passenger_identity_id
            )
            .join(
                MobilePassengerSessionIdentityModel,
                and_(
                    MobilePassengerSessionIdentityModel.gc_group_access_id
                    == GCGroupAccessModel.id,
                    MobilePassengerSessionIdentityModel.agency_id
                    == GCGroupAccessModel.agency_id,
                    MobilePassengerSessionIdentityModel.group_id
                    == GCGroupAccessModel.group_id,
                ),
            )
            .join(
                MobilePassengerIdentityModel,
                and_(
                    MobilePassengerIdentityModel.id
                    == MobilePassengerSessionIdentityModel.passenger_identity_id,
                    MobilePassengerIdentityModel.gc_group_access_id
                    == MobilePassengerSessionIdentityModel.gc_group_access_id,
                    MobilePassengerIdentityModel.agency_id
                    == MobilePassengerSessionIdentityModel.agency_id,
                    MobilePassengerIdentityModel.group_id
                    == MobilePassengerSessionIdentityModel.group_id,
                ),
            )
            .where(
                GCGroupAccessModel.passenger_access_enabled.is_(True),
                MobilePassengerSessionIdentityModel.session_id == claims.session_id,
                MobilePassengerSessionIdentityModel.agency_id == claims.agency_id,
                MobilePassengerIdentityModel.claim_generation
                == MobilePassengerSessionIdentityModel.identity_claim_generation,
                MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                MobilePassengerIdentityModel.revoked_at.is_(None),
            )
        )
    elif claims.principal_type == "client_manager":
        statement = (
            statement.join(
                ClientManagerGroupAssignmentModel,
                ClientManagerGroupAssignmentModel.gc_group_access_id == GCGroupAccessModel.id,
            )
            .join(
                ClientManagerProfileModel,
                ClientManagerProfileModel.id
                == ClientManagerGroupAssignmentModel.profile_id,
            )
            .where(
                GCGroupAccessModel.client_manager_access_enabled.is_(True),
                ClientManagerProfileModel.user_id == claims.principal_id,
                ClientManagerProfileModel.agency_id == claims.agency_id,
                ClientManagerProfileModel.status == "active",
                ClientManagerProfileModel.deleted_at.is_(None),
                ClientManagerGroupAssignmentModel.agency_id == claims.agency_id,
                ClientManagerGroupAssignmentModel.group_id == ClientGroupModel.id,
                ClientManagerGroupAssignmentModel.is_active.is_(True),
                ClientManagerGroupAssignmentModel.revoked_at.is_(None),
            )
        )
    elif claims.principal_type == "coordinator":
        statement = statement.join(
            CoordinatorGroupAssignmentModel,
            CoordinatorGroupAssignmentModel.group_id == ClientGroupModel.id,
        ).where(
            GCGroupAccessModel.coordinator_access_enabled.is_(True),
            CoordinatorGroupAssignmentModel.coordinator_user_id == claims.principal_id,
            CoordinatorGroupAssignmentModel.agency_id == claims.agency_id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
    else:  # Defensive guard for future token-claim changes.
        raise AuthorizationError("Mobile trip access is not available")

    if cursor is not None:
        statement = statement.where(ClientGroupModel.id > cursor)
    result = await session.execute(
        statement.order_by(ClientGroupModel.id).limit(limit + 1)
    )
    rows = list(result.all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        _trip_summary(row[1], row[0], claims.principal_type)
        for row in rows
    ]
    return MobileTripsResponse(
        items=items,
        next_cursor=str(rows[-1][1].id) if has_more and rows else None,
    )


@router.get("/trips/{group_id}/manifest", response_model=MobileManifestResponse)
async def get_mobile_manifest(
    group_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileManifestResponse:
    trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)
    max_sequence = (
        await session.execute(
            select(func.coalesce(func.max(MobileSyncChangeModel.sequence), 0)).where(
                MobileSyncChangeModel.agency_id == claims.agency_id,
                MobileSyncChangeModel.gc_group_access_id == trip.access.id,
                MobileSyncChangeModel.access_generation == trip.access.access_generation,
            )
        )
    ).scalar_one()
    prefix = f"/api/v1/mobile/trips/{group_id}"
    versions = await _mobile_manifest_versions(session, claims=claims, trip=trip)
    return MobileManifestResponse(
        trip=_trip_summary(trip.group, trip.access, claims.principal_type),
        sync_cursor=int(max_sequence),
        server_time=datetime.now(tz=UTC),
        access_expires_at=trip.access.access_expires_at,
        versions=versions,
        resources=MobileManifestResources(
            itinerary=f"{prefix}/itinerary",
            announcements=f"{prefix}/announcements",
            common_documents=f"{prefix}/common-documents",
            personal_documents=f"{prefix}/documents",
            room=f"{prefix}/room",
            meals=f"{prefix}/meals",
            qr=f"{prefix}/qr",
            sync_changes=f"/api/v1/mobile/sync/changes?trip_id={group_id}",
        ),
    )


@router.get("/sync/changes", response_model=MobileSyncPageResponse)
async def list_mobile_sync_changes(
    trip_id: uuid.UUID = Query(...),
    cursor: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=_MAX_SYNC_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileSyncPageResponse:
    trip = await MobileAccessPolicy(session).require_trip_access(claims, trip_id)
    now = datetime.now(tz=UTC)
    scope_filters = (
        MobileSyncChangeModel.agency_id == claims.agency_id,
        MobileSyncChangeModel.gc_group_access_id == trip.access.id,
        MobileSyncChangeModel.group_id == trip_id,
        MobileSyncChangeModel.access_generation == trip.access.access_generation,
    )
    # Capture the scoped journal watermark before reading the audience-specific
    # page. Rows appended afterwards have a greater sequence and remain visible
    # to the next request. This lets a device advance across expired or
    # permanently invisible journal gaps without skipping a deliverable row.
    high_water = int(
        (
            await session.execute(
                select(func.coalesce(func.max(MobileSyncChangeModel.sequence), 0)).where(
                    *scope_filters
                )
            )
        ).scalar_one()
    )
    statement = select(MobileSyncChangeModel).where(
        *scope_filters,
        MobileSyncChangeModel.sequence > cursor,
        MobileSyncChangeModel.sequence <= high_water,
        or_(
            MobileSyncChangeModel.expires_at.is_(None),
            MobileSyncChangeModel.expires_at > now,
        ),
        MobileSyncChangeModel.audience.in_(("all", claims.principal_type)),
    )
    if claims.principal_type == "passenger":
        identity = _passenger_identity(trip)
        statement = statement.where(
            or_(
                MobileSyncChangeModel.passenger_identity_id.is_(None),
                MobileSyncChangeModel.passenger_identity_id == identity.id,
            )
        )
    else:
        statement = statement.where(MobileSyncChangeModel.passenger_identity_id.is_(None))

    result = await session.execute(
        statement.order_by(MobileSyncChangeModel.sequence).limit(limit + 1)
    )
    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    changes = [
        MobileSyncChangeResponse(
            sequence=row.sequence,
            group_id=row.group_id,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            operation="upsert" if row.operation == "publish" else row.operation,
            version=row.version,
            occurred_at=row.occurred_at,
            payload=_safe_sync_payload(row.payload),
        )
        for row in rows
    ]
    next_cursor = (
        rows[-1].sequence
        if has_more
        else max(cursor, high_water)
    )
    return MobileSyncPageResponse(
        changes=changes,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.post(
    "/sync/ack",
    response_model=MobileSyncAcknowledgementResponse,
)
async def acknowledge_mobile_sync(
    body: MobileSyncAcknowledgementRequest,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileSyncAcknowledgementResponse:
    """Acknowledge a durable, fully refreshed local sync snapshot.

    The acknowledgement is deliberately not a sync mutation and therefore
    never appends to the change journal.  It is accepted only for the live
    access generation, a non-future journal cursor, and the exact current
    resource revisions the client says it committed locally.
    """

    trip = await MobileAccessPolicy(session).require_trip_access(claims, body.trip_id)
    if body.access_generation != trip.access.access_generation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sync state changed; refresh and retry",
        )
    high_water = int(
        (
            await session.execute(
                select(func.coalesce(func.max(MobileSyncChangeModel.sequence), 0)).where(
                    MobileSyncChangeModel.agency_id == claims.agency_id,
                    MobileSyncChangeModel.gc_group_access_id == trip.access.id,
                    MobileSyncChangeModel.access_generation
                    == trip.access.access_generation,
                )
            )
        ).scalar_one()
        or 0
    )
    if body.cursor > high_water:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sync state changed; refresh and retry",
        )
    current_versions = await _mobile_manifest_versions(
        session,
        claims=claims,
        trip=trip,
    )
    if not hmac.compare_digest(
        current_versions.model_dump_json(),
        body.versions.model_dump_json(),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sync state changed; refresh and retry",
        )
    device_session = (
        await session.execute(
            select(MobileDeviceSessionModel)
            .where(
                MobileDeviceSessionModel.id == claims.session_id,
                MobileDeviceSessionModel.agency_id == claims.agency_id,
                MobileDeviceSessionModel.status == "active",
                MobileDeviceSessionModel.session_generation
                == claims.session_generation,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if device_session is None:
        raise AuthenticationError("Mobile session is no longer active")
    acknowledged_at = datetime.now(tz=UTC)
    device_session.selected_gc_group_access_id = trip.access.id
    device_session.selected_group_id = trip.group.id
    device_session.last_seen_at = acknowledged_at
    device_session.last_sync_acknowledged_at = acknowledged_at
    trip.access.last_successful_sync_at = acknowledged_at
    await session.flush()
    return MobileSyncAcknowledgementResponse(
        trip_id=body.trip_id,
        cursor=body.cursor,
        access_generation=body.access_generation,
        acknowledged_at=acknowledged_at,
    )


@router.get("/trips/{group_id}/itinerary", response_model=MobileItineraryResponse)
async def get_mobile_itinerary(
    group_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileItineraryResponse:
    trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)
    now = datetime.now(tz=UTC)
    itinerary = (
        await session.execute(
            select(GCItineraryVersionModel)
            .where(
                GCItineraryVersionModel.agency_id == claims.agency_id,
                GCItineraryVersionModel.group_id == group_id,
                GCItineraryVersionModel.gc_group_access_id == trip.access.id,
                GCItineraryVersionModel.status == "published",
                or_(
                    GCItineraryVersionModel.availability_starts_at.is_(None),
                    GCItineraryVersionModel.availability_starts_at <= now,
                ),
                or_(
                    GCItineraryVersionModel.availability_expires_at.is_(None),
                    GCItineraryVersionModel.availability_expires_at > now,
                ),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if itinerary is None or itinerary.published_at is None:
        raise EntityNotFoundError("Published mobile itinerary", group_id)

    day_rows = list(
        (
            await session.execute(
                select(GCItineraryDayModel)
                .where(
                    GCItineraryDayModel.itinerary_version_id == itinerary.id,
                    GCItineraryDayModel.gc_group_access_id == trip.access.id,
                    GCItineraryDayModel.agency_id == claims.agency_id,
                    GCItineraryDayModel.group_id == group_id,
                )
                .order_by(
                    GCItineraryDayModel.sort_order,
                    GCItineraryDayModel.day_number,
                )
                .limit(365)
            )
        ).scalars()
    )
    day_ids = [item.id for item in day_rows]
    item_rows = []
    if day_ids:
        item_rows = list(
            (
                await session.execute(
                    select(GCItineraryItemModel)
                    .where(
                        GCItineraryItemModel.itinerary_version_id == itinerary.id,
                        GCItineraryItemModel.itinerary_day_id.in_(day_ids),
                        GCItineraryItemModel.gc_group_access_id == trip.access.id,
                        GCItineraryItemModel.agency_id == claims.agency_id,
                        GCItineraryItemModel.group_id == group_id,
                    )
                    .order_by(
                        GCItineraryItemModel.itinerary_day_id,
                        GCItineraryItemModel.sort_order,
                    )
                    .limit(1500)
                )
            ).scalars()
        )
    by_day: dict[uuid.UUID, list[MobileItineraryItemResponse]] = {
        day_id: [] for day_id in day_ids
    }
    for item in item_rows:
        bucket = by_day.get(item.itinerary_day_id)
        if bucket is None or len(bucket) >= 250:
            continue
        bucket.append(
            MobileItineraryItemResponse(
                id=item.id,
                title=item.title,
                description=item.description,
                starts_at=item.starts_at,
                ends_at=item.ends_at,
                location_name=item.location_name,
                latitude=item.latitude,
                longitude=item.longitude,
                sort_order=item.sort_order,
            )
        )
    return MobileItineraryResponse(
        trip_id=group_id,
        version=itinerary.version,
        title=itinerary.title,
        published_at=itinerary.published_at,
        days=[
            MobileItineraryDayResponse(
                id=day.id,
                day_number=day.day_number,
                trip_date=day.trip_date,
                title=day.title,
                sort_order=day.sort_order,
                items=by_day[day.id],
            )
            for day in day_rows
        ],
    )


@router.get(
    "/trips/{group_id}/announcements",
    response_model=MobileAnnouncementPageResponse,
)
async def list_mobile_announcements(
    group_id: uuid.UUID,
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=_MAX_ANNOUNCEMENT_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAnnouncementPageResponse:
    trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)
    now = datetime.now(tz=UTC)
    visibility = getattr(GCAnnouncementModel, f"{claims.principal_type}_visible")
    statement = select(GCAnnouncementModel).where(
        GCAnnouncementModel.agency_id == claims.agency_id,
        GCAnnouncementModel.group_id == group_id,
        GCAnnouncementModel.gc_group_access_id == trip.access.id,
        GCAnnouncementModel.status == "published",
        visibility.is_(True),
        or_(
            GCAnnouncementModel.availability_starts_at.is_(None),
            GCAnnouncementModel.availability_starts_at <= now,
        ),
        or_(
            GCAnnouncementModel.availability_expires_at.is_(None),
            GCAnnouncementModel.availability_expires_at > now,
        ),
    )
    if cursor is not None:
        statement = statement.where(GCAnnouncementModel.id < cursor)
    rows = list(
        (
            await session.execute(
                statement.order_by(GCAnnouncementModel.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return MobileAnnouncementPageResponse(
        items=[
            MobileAnnouncementResponse(
                id=item.id,
                trip_id=group_id,
                version=item.version,
                title=item.title,
                message=item.body,
                priority=_mobile_announcement_priority(item.priority),
                published_at=_required_published_at(item.published_at, "announcement", item.id),
                available_until=item.availability_expires_at,
                is_read=False,
            )
            for item in rows
        ],
        next_cursor=str(rows[-1].id) if has_more and rows else None,
    )


@router.get(
    "/trips/{group_id}/common-documents",
    response_model=MobileCommonDocumentPageResponse,
)
async def list_mobile_common_documents(
    group_id: uuid.UUID,
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=_MAX_DOCUMENT_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileCommonDocumentPageResponse:
    trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)
    now = datetime.now(tz=UTC)
    visibility = getattr(GCCommonDocumentModel, f"{claims.principal_type}_visible")
    statement = select(GCCommonDocumentModel).where(
        GCCommonDocumentModel.agency_id == claims.agency_id,
        GCCommonDocumentModel.group_id == group_id,
        GCCommonDocumentModel.gc_group_access_id == trip.access.id,
        GCCommonDocumentModel.status == "published",
        visibility.is_(True),
        or_(
            GCCommonDocumentModel.availability_starts_at.is_(None),
            GCCommonDocumentModel.availability_starts_at <= now,
        ),
        or_(
            GCCommonDocumentModel.availability_expires_at.is_(None),
            GCCommonDocumentModel.availability_expires_at > now,
        ),
    )
    if cursor is not None:
        statement = statement.where(GCCommonDocumentModel.id > cursor)
    rows = list(
        (
            await session.execute(
                statement.order_by(GCCommonDocumentModel.id).limit(limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return MobileCommonDocumentPageResponse(
        items=[
            MobileCommonDocumentResponse(
                id=item.id,
                logical_document_id=item.logical_document_id,
                trip_id=group_id,
                category=item.category,
                title=item.title,
                description=item.description,
                media_type=item.media_type,
                byte_size=item.byte_size,
                checksum_sha256=item.checksum_sha256,
                version=item.version,
                offline_available=item.offline_available,
                published_at=_required_published_at(
                    item.published_at, "common document", item.id
                ),
                updated_at=item.updated_at,
            )
            for item in rows
        ],
        next_cursor=str(rows[-1].id) if has_more and rows else None,
    )


@router.get(
    "/trips/{group_id}/documents",
    response_model=MobilePersonalDocumentPageResponse,
)
@router.get(
    "/trips/{group_id}/personal-documents",
    response_model=MobilePersonalDocumentPageResponse,
    include_in_schema=False,
)
async def list_mobile_personal_documents(
    group_id: uuid.UUID,
    response: Response,
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=_MAX_PERSONAL_DOCUMENTS),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobilePersonalDocumentPageResponse:
    """Return only passenger-owned metadata; never return storage locations."""

    trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)
    page_sources = await _personal_document_sources(
        session,
        claims,
        trip,
        cursor=cursor,
        limit=limit + 1,
    )
    has_more = len(page_sources) > limit
    page_sources = page_sources[:limit]

    cache_by_source = await _document_cache_by_source(
        session,
        agency_id=claims.agency_id,
        sources=page_sources,
    )
    items: list[MobilePersonalDocumentResponse] = []
    pending_count = 0
    for source in page_sources:
        cache = cache_by_source.get(_source_key(source))
        if not _cache_matches_source(cache, source):
            # Keep list requests metadata-only. The native client authorizes
            # pending Passport/Visa/Ticket entries, and that owned, single-file
            # request performs any one-time legacy checksum repair before download.
            pending_count += 1
            items.append(_pending_personal_document_response(source, trip, cache))
        else:
            items.append(_personal_document_response(source, cache))
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-GC-Metadata-Pending"] = str(pending_count)
    return MobilePersonalDocumentPageResponse(
        items=items,
        next_cursor=(
            str(page_sources[-1].document_id)
            if has_more and page_sources
            else None
        ),
    )


@router.post(
    "/trips/{group_id}/documents/{document_id}/authorize",
    response_model=MobileDocumentAuthorizationResponse,
)
async def authorize_mobile_document_download(
    group_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    version: int = Query(..., ge=1),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileDocumentAuthorizationResponse:
    trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)
    source, resolved_version = await _resolve_mobile_document(
        session,
        claims=claims,
        trip=trip,
        document_id=document_id,
    )
    if version != resolved_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document metadata changed; synchronize and retry",
        )
    # Resolving a legacy/passport source materializes authoritative integrity
    # metadata when needed. Returning it with the short-lived grant lets a
    # first-login client safely download a document that was still reported as
    # `pending` by the metadata-first list, without weakening byte/checksum
    # validation or requiring repeated polling.
    expected_size, expected_checksum = await _document_integrity_metadata(
        session,
        claims=claims,
        trip=trip,
        source=source,
    )
    token, expires_at = create_mobile_document_grant(
        claims=claims,
        gc_group_access_id=trip.access.id,
        group_id=group_id,
        access_generation=trip.access.access_generation,
        document_id=document_id,
        document_version=resolved_version,
        document_scope="personal" if source.scope == "personal" else "common",
        passenger_identity_id=source.passenger_identity_id,
    )
    await _audit_document_access(
        session,
        request,
        claims=claims,
        group_id=group_id,
        document_id=document_id,
        scope=source.scope,
        action="mobile.document_download_authorized",
    )
    return MobileDocumentAuthorizationResponse(
        document_id=document_id,
        version=resolved_version,
        size_bytes=expected_size,
        checksum_sha256=expected_checksum,
        content_type=source.content_type,
        content_path=(
            f"/api/v1/mobile/trips/{group_id}/documents/{document_id}/content"
            f"?version={resolved_version}"
        ),
        download_token=token,
        expires_at=expires_at,
    )


@router.get(
    "/trips/{group_id}/documents/{document_id}/content",
    response_class=StreamingResponse,
)
@router.get(
    "/trips/{group_id}/common-documents/{document_id}/content",
    response_class=StreamingResponse,
    include_in_schema=False,
)
@router.get(
    "/trips/{group_id}/personal-documents/{document_id}/content",
    response_class=StreamingResponse,
    include_in_schema=False,
)
async def download_mobile_document_content(
    group_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    version: int = Query(..., ge=1),
    download_token: str = Header(..., alias="X-GC-Download-Token"),
    range_header: str | None = Header(default=None, alias="Range"),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)
    source, resolved_version = await _resolve_mobile_document(
        session,
        claims=claims,
        trip=trip,
        document_id=document_id,
    )
    if version != resolved_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document metadata changed; synchronize and retry",
        )
    grant = decode_mobile_document_grant(download_token)
    validate_mobile_document_grant(
        grant,
        access_claims=claims,
        gc_group_access_id=trip.access.id,
        group_id=group_id,
        access_generation=trip.access.access_generation,
        document_id=document_id,
        document_version=resolved_version,
        document_scope="personal" if source.scope == "personal" else "common",
        passenger_identity_id=source.passenger_identity_id,
    )
    expected_size, expected_checksum = await _document_integrity_metadata(
        session,
        claims=claims,
        trip=trip,
        source=source,
    )
    maximum_size = (
        get_settings().mobile.personal_document_max_bytes
        if source.scope == "personal"
        else get_settings().mobile.common_document_max_bytes
    )
    if expected_size < 1 or expected_size > maximum_size:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Document is outside the mobile offline-storage limit",
        )
    storage = MinioStorageRepository()
    signature = await storage.get_file_range(
        source.storage_key,
        start=0,
        end=min(expected_size, 16) - 1,
    )
    _validate_document_signature(signature, source.content_type)
    range_start = _mobile_document_range_start(range_header, expected_size)
    response_start = range_start or 0
    await _audit_document_access(
        session,
        request,
        claims=claims,
        group_id=group_id,
        document_id=document_id,
        scope=source.scope,
        action="mobile.document_downloaded",
    )

    # Copy only immutable, already-authorized values into the stream plan.
    # Committing persists the audit (and any bounded legacy metadata repair),
    # while close immediately returns the checked-out connection to the pool.
    # FastAPI's dependency finalizer can safely close/commit the reset session
    # again; no ORM state or database operation is used after this boundary.
    stream_plan = _MobileDocumentStreamPlan(
        storage_key=source.storage_key,
        safe_filename=source.safe_filename,
        content_type=source.content_type,
        expected_size=expected_size,
        expected_checksum=expected_checksum,
        response_start=response_start,
        is_partial=range_start is not None,
    )
    await session.commit()
    await session.close()

    async def chunks():  # type: ignore[no-untyped-def]
        async with _MOBILE_DOCUMENT_STREAM_SLOTS:
            # Explicitly close the S3 response body when the client cancels,
            # the ASGI task is cancelled, or validation fails mid-stream.
            async with aclosing(
                storage.stream_file(
                    stream_plan.storage_key,
                    start=stream_plan.response_start,
                    expected_bytes=(
                        stream_plan.expected_size - stream_plan.response_start
                    ),
                )
            ) as object_stream:
                async for chunk in object_stream:
                    yield chunk

    encoded_name = quote(stream_plan.safe_filename, safe="")
    response_headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-store, max-age=0",
        "Pragma": "no-cache",
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        "Content-Length": str(
            stream_plan.expected_size - stream_plan.response_start
        ),
        "Content-Security-Policy": "sandbox",
        "ETag": f'"sha256-{stream_plan.expected_checksum}"',
        "X-Content-Type-Options": "nosniff",
    }
    if stream_plan.is_partial:
        response_headers["Content-Range"] = (
            f"bytes {stream_plan.response_start}-{stream_plan.expected_size - 1}/"
            f"{stream_plan.expected_size}"
        )
    return StreamingResponse(
        chunks(),
        media_type=stream_plan.content_type,
        status_code=(
            status.HTTP_206_PARTIAL_CONTENT
            if stream_plan.is_partial
            else status.HTTP_200_OK
        ),
        headers=response_headers,
    )


@router.get("/trips/{group_id}/room", response_model=MobileRoomResponse)
async def get_mobile_room(
    group_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileRoomResponse:
    trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)
    identity = _passenger_identity(trip)
    passenger_id = identity.passenger_submission_id
    rooming_revision = await _passenger_rooming_revision(session, claims, trip)
    today = date.today()
    row = (
        await session.execute(
            select(RoomingAssignmentModel, RoomingRoomModel, RoomingHotelModel)
            .join(RoomingRoomModel, RoomingRoomModel.id == RoomingAssignmentModel.room_id)
            .join(RoomingHotelModel, RoomingHotelModel.id == RoomingAssignmentModel.hotel_id)
            .where(
                RoomingAssignmentModel.passenger_id == passenger_id,
                RoomingHotelModel.agency_id == claims.agency_id,
                RoomingHotelModel.group_id == group_id,
                RoomingRoomModel.hotel_id == RoomingHotelModel.id,
            )
            .order_by(
                case((RoomingHotelModel.check_out_date >= today, 0), else_=1),
                RoomingHotelModel.check_in_date,
                RoomingHotelModel.id,
            )
            .limit(1)
        )
    ).first()
    if row is None:
        return MobileRoomResponse(
            id=_scoped_projection_id(_ROOM_NAMESPACE, group_id, passenger_id),
            trip_id=group_id,
            passenger_id=passenger_id,
            hotel_name=None,
            room_number=None,
            roommate_summary=None,
            version=rooming_revision,
            updated_at=trip.access.updated_at,
        )
    assignment, room, hotel = row
    occupant_count = (
        await session.execute(
            select(func.count(RoomingAssignmentModel.id)).where(
                RoomingAssignmentModel.hotel_id == hotel.id,
                RoomingAssignmentModel.room_id == room.id,
            )
        )
    ).scalar_one()
    other_count = max(0, int(occupant_count) - 1)
    roommate_summary = (
        f"Shared with {other_count} other traveller"
        + ("s" if other_count != 1 else "")
        if other_count
        else None
    )
    return MobileRoomResponse(
        id=assignment.id,
        trip_id=group_id,
        passenger_id=passenger_id,
        hotel_name=hotel.hotel_name,
        room_number=room.room_number,
        roommate_summary=roommate_summary,
        version=rooming_revision,
        updated_at=max(assignment.assigned_at, room.updated_at, hotel.updated_at),
    )


@router.get("/trips/{group_id}/meals", response_model=MobileMealResponse)
async def get_mobile_meals(
    group_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileMealResponse:
    trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)
    identity = _passenger_identity(trip)
    submission = (
        await session.execute(
            select(PassportSubmissionModel).where(
                PassportSubmissionModel.id == identity.passenger_submission_id,
                PassportSubmissionModel.agency_id == claims.agency_id,
                PassportSubmissionModel.group_id == group_id,
            )
        )
    ).scalar_one_or_none()
    if submission is None:
        raise AuthorizationError("Passenger resource is not available")
    preference = _mobile_meal_preference(
        submission.confirmed_fields,
        submission.staff_metadata,
    )
    return MobileMealResponse(
        id=_scoped_projection_id(_MEAL_NAMESPACE, group_id, submission.id),
        trip_id=group_id,
        passenger_id=submission.id,
        preference=preference,
        notes=None,
        version=_passenger_meal_revision(
            fallback_version=trip.access.meal_version,
            updated_at=submission.updated_at,
            preference=preference,
        ),
        updated_at=submission.updated_at,
    )


@router.get("/trips/{group_id}/qr", response_model=MobileQRResponse)
async def get_mobile_qr(
    group_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileQRResponse:
    trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)
    identity = _passenger_identity(trip)
    now = datetime.now(tz=UTC)
    token = (
        await session.execute(
            select(PassengerQRTokenModel)
            .join(
                PassportSubmissionModel,
                PassportSubmissionModel.id == PassengerQRTokenModel.passenger_id,
            )
            .where(
                PassengerQRTokenModel.agency_id == claims.agency_id,
                PassengerQRTokenModel.passenger_id == identity.passenger_submission_id,
                PassengerQRTokenModel.is_active.is_(True),
                PassengerQRTokenModel.revoked_at.is_(None),
                PassengerQRTokenModel.expires_at > now,
                PassengerQRTokenModel.qr_payload.is_not(None),
                PassportSubmissionModel.agency_id == claims.agency_id,
                PassportSubmissionModel.group_id == group_id,
            )
            .order_by(PassengerQRTokenModel.token_version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if token is None or token.qr_payload is None:
        token = await ensure_mobile_passenger_qr(
            session,
            agency_id=claims.agency_id,
            group_id=group_id,
            passenger_id=identity.passenger_submission_id,
        )
    if token is None or token.qr_payload is None:
        raise EntityNotFoundError("Passenger QR", identity.passenger_submission_id)
    qr_revision = await _passenger_qr_revision(session, claims, trip)
    valid_until = token.expires_at
    if (
        trip.access.access_expires_at is not None
        and trip.access.access_expires_at < valid_until
    ):
        valid_until = trip.access.access_expires_at
    return MobileQRResponse(
        id=token.id,
        trip_id=group_id,
        passenger_id=identity.passenger_submission_id,
        signed_payload=token.qr_payload,
        version=qr_revision,
        valid_from=token.created_at,
        valid_until=valid_until,
        offline_allowed=valid_until > now,
        updated_at=token.updated_at,
    )


@router.get(
    "/manager/groups/{group_id}/readiness",
    response_model=MobileManagerReadinessResponse,
)
async def get_mobile_manager_readiness(
    group_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileManagerReadinessResponse:
    if claims.principal_type != "client_manager":
        raise AuthorizationError("Client Manager group access is required")
    trip = await MobileAccessPolicy(session).require_trip_access(claims, group_id)

    confirmed_meal = func.nullif(
        func.btrim(
            func.coalesce(
                PassportSubmissionModel.confirmed_fields["meal_preference"].as_string(),
                "",
            )
        ),
        "",
    )
    staff_meal = func.nullif(
        func.btrim(
            func.coalesce(
                PassportSubmissionModel.staff_metadata["meal_preference"].as_string(),
                "",
            )
        ),
        "",
    )
    passenger_count, passports_complete, meals_confirmed = (
        await session.execute(
            select(
                func.count(PassportSubmissionModel.id),
                func.count(
                    case(
                        (
                            PassportSubmissionModel.status.in_(
                                OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
                            ),
                            PassportSubmissionModel.id,
                        )
                    )
                ),
                func.count(
                    case(
                        (
                            func.coalesce(confirmed_meal, staff_meal, "")
                            != "",
                            PassportSubmissionModel.id,
                        )
                    )
                ),
            ).where(
                PassportSubmissionModel.agency_id == claims.agency_id,
                PassportSubmissionModel.group_id == group_id,
            )
        )
    ).one()
    document_counts = dict(
        (
            await session.execute(
                select(
                    DistributedDocumentModel.document_type,
                    func.count(func.distinct(DistributedDocumentModel.passenger_id)),
                )
                .where(
                    DistributedDocumentModel.agency_id == claims.agency_id,
                    DistributedDocumentModel.group_id == group_id,
                    DistributedDocumentModel.passenger_id.is_not(None),
                    DistributedDocumentModel.match_status == "matched",
                    DistributedDocumentModel.document_type.in_(
                        tuple(MOBILE_PERSONAL_DOCUMENT_TYPES)
                    ),
                )
                .group_by(DistributedDocumentModel.document_type)
            )
        ).all()
    )
    rooms_assigned = (
        await session.execute(
            select(func.count(func.distinct(RoomingAssignmentModel.passenger_id)))
            .join(RoomingHotelModel, RoomingHotelModel.id == RoomingAssignmentModel.hotel_id)
            .where(
                RoomingHotelModel.agency_id == claims.agency_id,
                RoomingHotelModel.group_id == group_id,
            )
        )
    ).scalar_one()
    passenger_total = int(passenger_count or 0)
    passport_total = int(passports_complete or 0)
    visa_total = int(document_counts.get("visa", 0))
    ticket_total = int(
        (
            await session.execute(
                select(func.count(func.distinct(DistributedDocumentModel.passenger_id))).where(
                    DistributedDocumentModel.agency_id == claims.agency_id,
                    DistributedDocumentModel.group_id == group_id,
                    DistributedDocumentModel.passenger_id.is_not(None),
                    DistributedDocumentModel.match_status == "matched",
                    DistributedDocumentModel.document_type.in_(
                        tuple(FLIGHT_TICKET_DOCUMENT_TYPES)
                    ),
                )
            )
        ).scalar_one()
        or 0
    )
    readiness_revision = await _manager_readiness_revision(session, claims, trip)
    return MobileManagerReadinessResponse(
        trip_id=group_id,
        passenger_count=passenger_total,
        passports_complete=passport_total,
        visas_available=visa_total,
        tickets_available=ticket_total,
        items_needing_attention=(
            max(0, passenger_total - passport_total)
            + max(0, passenger_total - visa_total)
            + max(0, passenger_total - ticket_total)
        ),
        rooms_assigned=int(rooms_assigned or 0),
        meals_confirmed=int(meals_confirmed or 0),
        version=readiness_revision,
        updated_at=trip.access.updated_at,
    )


async def _passenger_rooming_revision(
    session: AsyncSession,
    claims: MobileAccessClaims,
    trip: AuthorizedMobileTrip,
) -> int:
    identity = _passenger_identity(trip)
    state = (
        await session.execute(
            select(
                func.count(RoomingAssignmentModel.id),
                func.max(RoomingAssignmentModel.assigned_at),
                func.max(RoomingRoomModel.updated_at),
                func.max(RoomingHotelModel.updated_at),
            )
            .join(
                RoomingRoomModel,
                RoomingRoomModel.id == RoomingAssignmentModel.room_id,
            )
            .join(
                RoomingHotelModel,
                RoomingHotelModel.id == RoomingAssignmentModel.hotel_id,
            )
            .where(
                RoomingAssignmentModel.passenger_id
                == identity.passenger_submission_id,
                RoomingHotelModel.agency_id == claims.agency_id,
                RoomingHotelModel.group_id == trip.group.id,
            )
        )
    ).one()
    if int(state[0] or 0) > 0:
        return _state_revision(*state)
    return trip.access.rooming_version


def _mobile_meal_preference(
    confirmed_fields: dict | None,
    staff_metadata: dict | None,
) -> str | None:
    for fields in (confirmed_fields, staff_metadata):
        value = (fields or {}).get("meal_preference")
        if isinstance(value, str) and value.strip():
            return value.strip()[:255]
    return None


def _passenger_meal_revision(
    *,
    fallback_version: int,
    updated_at: datetime | None,
    preference: str | None,
) -> int:
    if preference:
        return _state_revision(updated_at, preference)
    return fallback_version


async def _passenger_qr_revision(
    session: AsyncSession,
    claims: MobileAccessClaims,
    trip: AuthorizedMobileTrip,
) -> int:
    identity = _passenger_identity(trip)
    state = (
        await session.execute(
            select(
                func.count(PassengerQRTokenModel.id),
                func.max(PassengerQRTokenModel.token_version),
                func.max(PassengerQRTokenModel.updated_at),
            )
            .join(
                PassportSubmissionModel,
                PassportSubmissionModel.id == PassengerQRTokenModel.passenger_id,
            )
            .where(
                PassengerQRTokenModel.agency_id == claims.agency_id,
                PassengerQRTokenModel.passenger_id
                == identity.passenger_submission_id,
                PassportSubmissionModel.agency_id == claims.agency_id,
                PassportSubmissionModel.group_id == trip.group.id,
            )
        )
    ).one()
    if int(state[0] or 0) > 0:
        return _state_revision(*state)
    return trip.access.qr_version


async def _manager_readiness_revision(
    session: AsyncSession,
    claims: MobileAccessClaims,
    trip: AuthorizedMobileTrip,
) -> int:
    passenger_state = (
        await session.execute(
            select(
                func.count(PassportSubmissionModel.id),
                func.max(PassportSubmissionModel.updated_at),
            ).where(
                PassportSubmissionModel.agency_id == claims.agency_id,
                PassportSubmissionModel.group_id == trip.group.id,
            )
        )
    ).one()
    document_state = (
        await session.execute(
            select(
                func.count(DistributedDocumentModel.id),
                func.max(DistributedDocumentModel.updated_at),
            ).where(
                DistributedDocumentModel.agency_id == claims.agency_id,
                DistributedDocumentModel.group_id == trip.group.id,
                DistributedDocumentModel.passenger_id.is_not(None),
                DistributedDocumentModel.match_status == "matched",
                DistributedDocumentModel.document_type.in_(
                    tuple(MOBILE_PERSONAL_DOCUMENT_TYPES)
                ),
            )
        )
    ).one()
    room_state = (
        await session.execute(
            select(
                func.count(RoomingAssignmentModel.id),
                func.max(RoomingAssignmentModel.assigned_at),
                func.max(RoomingRoomModel.updated_at),
                func.max(RoomingHotelModel.updated_at),
            )
            .join(
                RoomingHotelModel,
                RoomingHotelModel.id == RoomingAssignmentModel.hotel_id,
            )
            .join(
                RoomingRoomModel,
                RoomingRoomModel.id == RoomingAssignmentModel.room_id,
            )
            .where(
                RoomingHotelModel.agency_id == claims.agency_id,
                RoomingHotelModel.group_id == trip.group.id,
            )
        )
    ).one()
    return _state_revision(*passenger_state, *document_state, *room_state)


async def _coordinator_roster_revision(
    session: AsyncSession,
    claims: MobileAccessClaims,
    trip: AuthorizedMobileTrip,
) -> int:
    return await coordinator_roster_revision(
        session,
        agency_id=claims.agency_id,
        group_id=trip.group.id,
    )


async def _mobile_manifest_versions(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    trip: AuthorizedMobileTrip,
) -> MobileManifestVersions:
    """Derive compact change fingerprints from authoritative mutable tables.

    Existing rooming, meal, QR, passport and document workflows predate the
    mobile journal.  These bounded aggregate fingerprints let a client detect
    their changes without polling full resources or scattering duplicate
    version-bump logic across every legacy mutation route.
    """

    personal_documents = readiness = roster = 0
    rooming = trip.access.rooming_version
    meals = trip.access.meal_version
    qr = trip.access.qr_version

    if claims.principal_type == "passenger":
        identity = _passenger_identity(trip)
        submission = (
            await session.execute(
                select(
                    PassportSubmissionModel.updated_at,
                    PassportSubmissionModel.image_s3_key,
                    PassportSubmissionModel.passport_back_s3_key,
                    PassportSubmissionModel.confirmed_fields,
                    PassportSubmissionModel.staff_metadata,
                ).where(
                    PassportSubmissionModel.id == identity.passenger_submission_id,
                    PassportSubmissionModel.agency_id == claims.agency_id,
                    PassportSubmissionModel.group_id == trip.group.id,
                )
            )
        ).first()
        distributed = (
            await session.execute(
                select(
                    func.count(func.distinct(DistributedDocumentModel.id)),
                    func.max(DistributedDocumentModel.updated_at),
                    func.max(DocumentWhatsAppDeliveryModel.status_updated_at),
                )
                .join(
                    DocumentWhatsAppDeliveryModel,
                    DocumentWhatsAppDeliveryModel.distributed_document_id
                    == DistributedDocumentModel.id,
                )
                .where(
                    DistributedDocumentModel.agency_id == claims.agency_id,
                    DistributedDocumentModel.group_id == trip.group.id,
                    DistributedDocumentModel.passenger_id
                    == identity.passenger_submission_id,
                    DistributedDocumentModel.match_status == "matched",
                    DocumentWhatsAppDeliveryModel.agency_id == claims.agency_id,
                    DocumentWhatsAppDeliveryModel.group_id == trip.group.id,
                    DocumentWhatsAppDeliveryModel.passenger_id
                    == identity.passenger_submission_id,
                    DocumentWhatsAppDeliveryModel.status.in_(
                        _MOBILE_RELEASED_DOCUMENT_DELIVERY_STATUSES
                    ),
                )
            )
        ).one()
        has_passport_file = bool(
            submission
            and (
                (
                    submission.image_s3_key
                    and not submission.image_s3_key.endswith(".placeholder")
                )
                or submission.passport_back_s3_key
            )
        )
        if has_passport_file or int(distributed[0] or 0) > 0:
            personal_documents = _state_revision(
                submission.updated_at if submission else None,
                submission.image_s3_key if submission else None,
                submission.passport_back_s3_key if submission else None,
                distributed[0],
                distributed[1],
                distributed[2],
            )

        rooming = await _passenger_rooming_revision(session, claims, trip)
        meal_preference = _mobile_meal_preference(
            submission.confirmed_fields if submission else None,
            submission.staff_metadata if submission else None,
        )
        meals = _passenger_meal_revision(
            fallback_version=trip.access.meal_version,
            updated_at=submission.updated_at if submission else None,
            preference=meal_preference,
        )
        qr = await _passenger_qr_revision(session, claims, trip)

    elif claims.principal_type == "client_manager":
        readiness = await _manager_readiness_revision(session, claims, trip)
    elif claims.principal_type == "coordinator":
        roster = await _coordinator_roster_revision(session, claims, trip)

    return MobileManifestVersions(
        manifest=trip.access.manifest_version,
        itinerary=trip.access.itinerary_version,
        common_documents=trip.access.common_document_version,
        personal_documents=personal_documents,
        announcements=trip.access.announcement_version,
        rooming=rooming,
        meals=meals,
        qr=qr,
        readiness=readiness,
        roster=roster,
    )


def _state_revision(*parts: object) -> int:
    normalized: list[str] = []
    meaningful = False
    for part in parts:
        if isinstance(part, datetime):
            value = part.astimezone(UTC).isoformat()
            meaningful = True
        elif part is None:
            value = "-"
        else:
            value = str(part)
            meaningful = meaningful or value not in {"", "0", "False"}
        normalized.append(value)
    if not meaningful:
        return 0
    digest = hashlib.blake2b("|".join(normalized).encode(), digest_size=8).digest()
    # Keep the opaque revision exactly representable by JavaScript/React Native.
    # The client contract uses a JSON number, whose portable integer ceiling is
    # Number.MAX_SAFE_INTEGER (2**53 - 1).
    revision = int.from_bytes(digest, "big") & ((1 << 53) - 1)
    return revision or 1


def _distributed_document_is_released_to_passenger() -> ColumnElement[bool]:
    """Gate distributed files on the existing passenger WhatsApp release flow."""

    return exists(
        select(1).where(
            DocumentWhatsAppDeliveryModel.distributed_document_id
            == DistributedDocumentModel.id,
            DocumentWhatsAppDeliveryModel.agency_id
            == DistributedDocumentModel.agency_id,
            DocumentWhatsAppDeliveryModel.group_id == DistributedDocumentModel.group_id,
            DocumentWhatsAppDeliveryModel.passenger_id
            == DistributedDocumentModel.passenger_id,
            DocumentWhatsAppDeliveryModel.status.in_(
                _MOBILE_RELEASED_DOCUMENT_DELIVERY_STATUSES
            ),
        )
    )


async def _personal_document_sources(
    session: AsyncSession,
    claims: MobileAccessClaims,
    trip: AuthorizedMobileTrip,
    *,
    cursor: uuid.UUID | None,
    limit: int,
) -> list[_MobileDocumentSource]:
    """Return one bounded, UUID-keyset page of passenger-owned documents."""

    if limit < 1 or limit > _MAX_PERSONAL_DOCUMENTS + 1:
        raise ValueError("Personal document source page is out of bounds")
    identity = _passenger_identity(trip)
    submission = await _passenger_document_submission(session, claims, trip)
    sources = [
        source
        for source in _passport_document_sources(submission, identity.id)
        if cursor is None or source.document_id > cursor
    ]

    statement = select(DistributedDocumentModel).where(
        DistributedDocumentModel.agency_id == claims.agency_id,
        DistributedDocumentModel.group_id == trip.group.id,
        DistributedDocumentModel.passenger_id == submission.id,
        DistributedDocumentModel.match_status == "matched",
        DistributedDocumentModel.content_type.in_(_ALLOWED_DOCUMENT_TYPES),
        _distributed_document_is_released_to_passenger(),
    )
    if cursor is not None:
        statement = statement.where(DistributedDocumentModel.id > cursor)
    distributed = list(
        (
            await session.execute(
                statement.order_by(DistributedDocumentModel.id).limit(limit)
            )
        ).scalars()
    )
    sources.extend(
        _distributed_document_source(document, identity.id, submission.id)
        for document in distributed
    )
    return sorted(sources, key=lambda item: item.document_id.int)[:limit]


async def _passenger_document_submission(
    session: AsyncSession,
    claims: MobileAccessClaims,
    trip: AuthorizedMobileTrip,
) -> PassportSubmissionModel:
    identity = _passenger_identity(trip)
    submission = (
        await session.execute(
            select(PassportSubmissionModel).where(
                PassportSubmissionModel.id == identity.passenger_submission_id,
                PassportSubmissionModel.agency_id == claims.agency_id,
                PassportSubmissionModel.group_id == trip.group.id,
            )
        )
    ).scalar_one_or_none()
    if submission is None:
        raise AuthorizationError("Passenger document access is not available")
    return submission


def _passport_document_sources(
    submission: PassportSubmissionModel,
    passenger_identity_id: uuid.UUID,
) -> list[_MobileDocumentSource]:
    sources: list[_MobileDocumentSource] = []
    if submission.image_s3_key and not submission.image_s3_key.endswith(".placeholder"):
        content_type = _image_content_type(submission.image_s3_key)
        sources.append(
            _MobileDocumentSource(
                document_id=uuid.uuid5(_PASSPORT_FRONT_NAMESPACE, str(submission.id)),
                scope="personal",
                category="passport",
                display_name="Passport",
                safe_filename=_safe_mobile_filename("passport", content_type),
                content_type=content_type,
                storage_key=submission.image_s3_key,
                source_kind="passport_front",
                source_id=submission.id,
                source_updated_at=submission.updated_at,
                passenger_identity_id=passenger_identity_id,
                passenger_submission_id=submission.id,
            )
        )
    if submission.passport_back_s3_key:
        content_type = _image_content_type(submission.passport_back_s3_key)
        sources.append(
            _MobileDocumentSource(
                document_id=uuid.uuid5(_PASSPORT_BACK_NAMESPACE, str(submission.id)),
                scope="personal",
                category="passport_back",
                display_name="Passport back",
                safe_filename=_safe_mobile_filename("passport-back", content_type),
                content_type=content_type,
                storage_key=submission.passport_back_s3_key,
                source_kind="passport_back",
                source_id=submission.id,
                source_updated_at=submission.updated_at,
                passenger_identity_id=passenger_identity_id,
                passenger_submission_id=submission.id,
            )
        )
    return sources


def _distributed_document_source(
    document: DistributedDocumentModel,
    passenger_identity_id: uuid.UUID,
    passenger_submission_id: uuid.UUID,
) -> _MobileDocumentSource:
    content_type = document.content_type.lower().split(";", 1)[0].strip()
    if content_type not in _ALLOWED_DOCUMENT_TYPES:
        # The query applies the same allow-list. Keep the conversion fail closed
        # if a malformed test double or unexpected database value reaches here.
        raise AuthorizationError("Passenger document access is not available")
    category = _mobile_document_category(document.document_type)
    safe_filename = _safe_mobile_filename(document.original_filename, content_type)
    lane = document_lane(document.document_type)
    return _MobileDocumentSource(
        document_id=document.id,
        scope="personal",
        category=category,
        display_name=(
            lane.label if lane is not None else _document_display_name(category, safe_filename)
        ),
        safe_filename=safe_filename,
        content_type=content_type,
        storage_key=document.storage_key,
        source_kind="distributed",
        source_id=document.id,
        source_updated_at=document.updated_at,
        passenger_identity_id=passenger_identity_id,
        passenger_submission_id=passenger_submission_id,
    )


async def _personal_document_source_by_id(
    session: AsyncSession,
    claims: MobileAccessClaims,
    trip: AuthorizedMobileTrip,
    document_id: uuid.UUID,
) -> _MobileDocumentSource | None:
    """Resolve one owned source without scanning or truncating a document page."""

    identity = _passenger_identity(trip)
    submission = await _passenger_document_submission(session, claims, trip)
    passport_source = next(
        (
            source
            for source in _passport_document_sources(submission, identity.id)
            if source.document_id == document_id
        ),
        None,
    )
    if passport_source is not None:
        return passport_source
    document = (
        await session.execute(
            select(DistributedDocumentModel).where(
                DistributedDocumentModel.id == document_id,
                DistributedDocumentModel.agency_id == claims.agency_id,
                DistributedDocumentModel.group_id == trip.group.id,
                DistributedDocumentModel.passenger_id == submission.id,
                DistributedDocumentModel.match_status == "matched",
                DistributedDocumentModel.content_type.in_(_ALLOWED_DOCUMENT_TYPES),
                _distributed_document_is_released_to_passenger(),
            )
        )
    ).scalar_one_or_none()
    if document is None:
        return None
    return _distributed_document_source(document, identity.id, submission.id)


async def _document_cache_by_source(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    sources: list[_MobileDocumentSource],
) -> dict[tuple[str, uuid.UUID], MobileDocumentMetadataCacheModel]:
    source_ids = [item.source_id for item in sources if item.scope == "personal"]
    if not source_ids:
        return {}
    rows = list(
        (
            await session.execute(
                select(MobileDocumentMetadataCacheModel).where(
                    MobileDocumentMetadataCacheModel.agency_id == agency_id,
                    MobileDocumentMetadataCacheModel.source_id.in_(source_ids),
                )
            )
        ).scalars()
    )
    return {(item.source_kind, item.source_id): item for item in rows}


def _source_key(source: _MobileDocumentSource) -> tuple[str, uuid.UUID]:
    return source.source_kind, source.source_id


def _cache_matches_source(
    cache: MobileDocumentMetadataCacheModel | None,
    source: _MobileDocumentSource,
) -> bool:
    if cache is None:
        return False
    expected_key_hash = hash_mobile_lookup(
        source.storage_key,
        purpose="document-storage-key",
    )
    return bool(
        cache.id == source.document_id
        and cache.storage_key_hash == expected_key_hash
        and cache.content_type == source.content_type
        and cache.source_updated_at == source.source_updated_at
        and cache.byte_size > 0
        and cache.checksum_sha256
    )


async def _materialize_personal_document_metadata(
    session: AsyncSession,
    *,
    trip: AuthorizedMobileTrip,
    identity: MobilePassengerIdentityModel,
    source: _MobileDocumentSource,
) -> MobileDocumentMetadataCacheModel:
    if source.scope != "personal" or source.passenger_identity_id != identity.id:
        raise AuthorizationError("Passenger document access is not available")
    byte_size, checksum = await _personal_document_source_integrity(source)
    key_hash = hash_mobile_lookup(
        source.storage_key,
        purpose="document-storage-key",
    )
    row = (
        await session.execute(
            select(MobileDocumentMetadataCacheModel)
            .where(
                MobileDocumentMetadataCacheModel.agency_id == trip.access.agency_id,
                MobileDocumentMetadataCacheModel.source_kind == source.source_kind,
                MobileDocumentMetadataCacheModel.source_id == source.source_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(tz=UTC)
    if row is None:
        candidate = MobileDocumentMetadataCacheModel(
            id=source.document_id,
            agency_id=trip.access.agency_id,
            group_id=trip.group.id,
            gc_group_access_id=trip.access.id,
            passenger_identity_id=identity.id,
            passenger_submission_id=identity.passenger_submission_id,
            source_kind=source.source_kind,
            source_id=source.source_id,
            storage_key_hash=key_hash,
            safe_filename=source.safe_filename,
            content_type=source.content_type,
            byte_size=byte_size,
            checksum_sha256=checksum,
            version=1,
            source_updated_at=source.source_updated_at,
            created_at=now,
            updated_at=now,
        )
        try:
            async with session.begin_nested():
                session.add(candidate)
                await session.flush()
            return candidate
        except IntegrityError:
            row = (
                await session.execute(
                    select(MobileDocumentMetadataCacheModel)
                    .where(
                        MobileDocumentMetadataCacheModel.agency_id
                        == trip.access.agency_id,
                        MobileDocumentMetadataCacheModel.source_kind
                        == source.source_kind,
                        MobileDocumentMetadataCacheModel.source_id == source.source_id,
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise

    changed_content = (
        not _cache_matches_source(row, source)
        or row.storage_key_hash != key_hash
        or row.checksum_sha256 != checksum
        or row.byte_size != byte_size
        or row.content_type != source.content_type
    )
    if changed_content:
        row.version += 1
    row.id = source.document_id
    row.group_id = trip.group.id
    row.gc_group_access_id = trip.access.id
    row.passenger_identity_id = identity.id
    row.passenger_submission_id = identity.passenger_submission_id
    row.storage_key_hash = key_hash
    row.safe_filename = source.safe_filename
    row.content_type = source.content_type
    row.byte_size = byte_size
    row.checksum_sha256 = checksum
    row.source_updated_at = source.source_updated_at
    row.updated_at = now
    await session.flush()
    return row


async def _personal_document_source_integrity(
    source: _MobileDocumentSource,
) -> tuple[int, str]:
    """Inspect one owned source without full-body materialization.

    New uploads take the stored-checksum fast path plus one bounded signature
    read. Legacy objects are hashed once as a bounded async stream; the caller
    then persists that digest in the account/group/passenger-scoped cache.
    """

    if source.scope != "personal":
        raise AuthorizationError("Passenger document access is not available")
    storage = MinioStorageRepository()
    object_metadata = await storage.stat_file(source.storage_key)
    maximum = get_settings().mobile.personal_document_max_bytes
    if object_metadata.size_bytes < 1 or object_metadata.size_bytes > maximum:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Personal document is outside the mobile offline-storage limit",
        )
    signature = await storage.get_file_range(
        source.storage_key,
        start=0,
        end=min(object_metadata.size_bytes, 16) - 1,
    )
    _validate_document_signature(signature, source.content_type)
    checksum = object_metadata.checksum_sha256
    if checksum is None:
        checksum = await storage.calculate_file_sha256(
            source.storage_key,
            expected_bytes=object_metadata.size_bytes,
        )
    return object_metadata.size_bytes, checksum


async def _resolve_mobile_document(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    trip: AuthorizedMobileTrip,
    document_id: uuid.UUID,
) -> tuple[_MobileDocumentSource, int]:
    now = datetime.now(tz=UTC)
    visibility = getattr(GCCommonDocumentModel, f"{claims.principal_type}_visible")
    common = (
        await session.execute(
            select(GCCommonDocumentModel).where(
                GCCommonDocumentModel.id == document_id,
                GCCommonDocumentModel.agency_id == claims.agency_id,
                GCCommonDocumentModel.group_id == trip.group.id,
                GCCommonDocumentModel.gc_group_access_id == trip.access.id,
                GCCommonDocumentModel.status == "published",
                visibility.is_(True),
                or_(
                    GCCommonDocumentModel.availability_starts_at.is_(None),
                    GCCommonDocumentModel.availability_starts_at <= now,
                ),
                or_(
                    GCCommonDocumentModel.availability_expires_at.is_(None),
                    GCCommonDocumentModel.availability_expires_at > now,
                ),
            )
        )
    ).scalar_one_or_none()
    if common is not None:
        return (
            _MobileDocumentSource(
                document_id=common.id,
                scope="common",
                category=common.category,
                display_name=common.title,
                safe_filename=_safe_mobile_filename(
                    common.safe_filename, common.media_type
                ),
                content_type=common.media_type,
                storage_key=common.storage_key,
                source_kind="common",
                source_id=common.id,
                source_updated_at=common.updated_at,
                passenger_identity_id=None,
                passenger_submission_id=None,
                common_document=common,
            ),
            common.version,
        )
    if claims.principal_type != "passenger":
        raise EntityNotFoundError("Mobile document", document_id)
    identity = _passenger_identity(trip)
    source = await _personal_document_source_by_id(
        session,
        claims,
        trip,
        document_id,
    )
    if source is None:
        raise EntityNotFoundError("Mobile document", document_id)
    cache = (
        await session.execute(
            select(MobileDocumentMetadataCacheModel).where(
                MobileDocumentMetadataCacheModel.id == source.document_id,
                MobileDocumentMetadataCacheModel.agency_id == claims.agency_id,
                MobileDocumentMetadataCacheModel.group_id == trip.group.id,
                MobileDocumentMetadataCacheModel.gc_group_access_id == trip.access.id,
                MobileDocumentMetadataCacheModel.passenger_identity_id == identity.id,
            )
        )
    ).scalar_one_or_none()
    if not _cache_matches_source(cache, source):
        cache = await _materialize_personal_document_metadata(
            session,
            trip=trip,
            identity=identity,
            source=source,
        )
    return source, cache.version


async def _document_integrity_metadata(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    trip: AuthorizedMobileTrip,
    source: _MobileDocumentSource,
) -> tuple[int, str]:
    if source.scope == "common" and source.common_document is not None:
        return source.common_document.byte_size, source.common_document.checksum_sha256
    cache = (
        await session.execute(
            select(MobileDocumentMetadataCacheModel).where(
                MobileDocumentMetadataCacheModel.id == source.document_id,
                MobileDocumentMetadataCacheModel.agency_id == claims.agency_id,
                MobileDocumentMetadataCacheModel.group_id == trip.group.id,
                MobileDocumentMetadataCacheModel.gc_group_access_id == trip.access.id,
                MobileDocumentMetadataCacheModel.passenger_identity_id
                == source.passenger_identity_id,
            )
        )
    ).scalar_one_or_none()
    if not _cache_matches_source(cache, source):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document metadata changed; synchronize and retry",
        )
    return cache.byte_size, cache.checksum_sha256


def _personal_document_response(
    source: _MobileDocumentSource,
    cache: MobileDocumentMetadataCacheModel,
) -> MobilePersonalDocumentResponse:
    if source.passenger_submission_id is None:
        raise AuthorizationError("Passenger document access is not available")
    return MobilePersonalDocumentResponse(
        id=source.document_id,
        trip_id=cache.group_id,
        passenger_id=source.passenger_submission_id,
        category=source.category,
        display_name=source.display_name,
        content_type=source.content_type,
        size_bytes=cache.byte_size,
        version=cache.version,
        checksum_sha256=cache.checksum_sha256,
        offline_available=True,
        metadata_state="ready",
        updated_at=cache.updated_at,
        revoked_at=None,
    )


def _pending_personal_document_response(
    source: _MobileDocumentSource,
    trip: AuthorizedMobileTrip,
    cache: MobileDocumentMetadataCacheModel | None,
) -> MobilePersonalDocumentResponse:
    if source.passenger_submission_id is None:
        raise AuthorizationError("Passenger document access is not available")
    return MobilePersonalDocumentResponse(
        id=source.document_id,
        trip_id=trip.group.id,
        passenger_id=source.passenger_submission_id,
        category=source.category,
        display_name=source.display_name,
        content_type=source.content_type,
        size_bytes=None,
        # A stale cache is materialized as exactly the next revision during
        # authorization. Advertising that revision up front prevents the first
        # tap after a replacement from requesting the stale version and receiving
        # a deterministic 409 before the client has any bytes cached.
        version=(cache.version + 1 if cache is not None else 1),
        checksum_sha256=None,
        offline_available=False,
        metadata_state="pending",
        updated_at=source.source_updated_at,
        revoked_at=None,
    )


async def _audit_document_access(
    session: AsyncSession,
    request: Request,
    *,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    document_id: uuid.UUID,
    scope: str,
    action: str,
) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type="mobile_document",
        agency_id=claims.agency_id,
        user_id=(claims.principal_id if claims.principal_type != "passenger" else None),
        entity_id=str(document_id),
        ip_address=trusted_client_ip(request),
        metadata={
            "group_id": str(group_id),
            "scope": scope,
            "principal_type": claims.principal_type,
        },
    )


def _image_content_type(storage_key: str) -> str:
    lowered = storage_key.casefold().split("?", 1)[0]
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def _safe_mobile_filename(value: str, content_type: str) -> str:
    leaf = PurePosixPath(value.replace("\\", "/")).name
    stem = PurePosixPath(leaf).stem
    stem = re.sub(r"[\x00-\x1f\x7f]+", "", stem)
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._")
    stem = stem[:180] or "travel-document"
    extension = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(content_type, ".bin")
    return f"{stem}{extension}"


def _validate_document_signature(payload: bytes, content_type: str) -> None:
    valid = {
        "application/pdf": payload.startswith(b"%PDF-"),
        "image/jpeg": payload.startswith(b"\xff\xd8\xff"),
        "image/png": payload.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": (
            len(payload) >= 12
            and payload.startswith(b"RIFF")
            and payload[8:12] == b"WEBP"
        ),
    }.get(content_type, False)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document content did not match its declared type",
        )


def _mobile_document_range_start(value: str | None, total_size: int) -> int | None:
    """Accept only the single open-ended byte range used by the encrypted client.

    Metadata carries the authoritative size/checksum and the encrypted client verifies
    the complete assembled payload before commit. The backend validates a bounded file
    signature then streams the requested range directly from object storage. Multiple
    and suffix ranges remain rejected to keep response behavior deterministic.
    """

    if value is None:
        return None
    matched = re.fullmatch(r"bytes=(0|[1-9][0-9]*)-", value.strip())
    if matched is None:
        raise HTTPException(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            detail="Requested document range is not supported",
            headers={"Content-Range": f"bytes */{total_size}"},
        )
    start = int(matched.group(1))
    if start >= total_size:
        raise HTTPException(
            status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE,
            detail="Requested document range is outside the file",
            headers={"Content-Range": f"bytes */{total_size}"},
        )
    return start


def _mobile_document_category(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    distribution_category = mobile_document_category(normalized)
    if distribution_category is not None:
        return distribution_category
    aliases = {
        "ticket": "flight_ticket",
        "insurance": "insurance",
        "hotel_voucher": "hotel_voucher",
    }
    return aliases.get(normalized, normalized[:80] or "other")


def _document_display_name(category: str, safe_filename: str) -> str:
    labels = {
        "flight_ticket": "Flight ticket",
        "visa": "Visa",
        "insurance": "Insurance",
        "hotel_voucher": "Hotel voucher",
    }
    return labels.get(category, PurePosixPath(safe_filename).stem.replace("_", " ")[:255])


def _trip_summary(
    group: ClientGroupModel,
    access: GCGroupAccessModel,
    role: str,
) -> MobileTripSummaryResponse:
    if role not in {"passenger", "client_manager", "coordinator"}:
        raise AuthorizationError("Mobile trip access is not available")
    return MobileTripSummaryResponse(
        id=group.id,
        name=group.name,
        destination=group.destination,
        travel_date=group.travel_date,
        return_date=group.return_date,
        role=role,
        access_generation=access.access_generation,
        itinerary_version=access.itinerary_version,
        common_document_version=access.common_document_version,
        announcement_version=access.announcement_version,
    )


def _passenger_identity(trip: AuthorizedMobileTrip) -> MobilePassengerIdentityModel:
    identity = trip.passenger_identity
    if trip.principal_type != "passenger" or identity is None:
        raise AuthorizationError("Passenger resource is not available")
    return identity


def _safe_sync_payload(payload: object) -> dict[str, object]:
    """Allow only navigation/version hints from the append-only journal."""

    if not isinstance(payload, dict):
        return {}
    safe: dict[str, object] = {}
    for key in ("resource_path", "itinerary_version_id"):
        value = payload.get(key)
        if isinstance(value, str) and len(value) <= 512:
            safe[key] = value
    roster_revision = payload.get("roster_revision")
    if (
        isinstance(roster_revision, int)
        and not isinstance(roster_revision, bool)
        and 0 <= roster_revision <= (1 << 53) - 1
    ):
        safe["roster_revision"] = roster_revision
    return safe


def _mobile_announcement_priority(value: str) -> str:
    if value == "emergency":
        return "emergency"
    if value == "high":
        return "important"
    return "normal"


def _required_published_at(
    value: datetime | None,
    entity_name: str,
    entity_id: uuid.UUID,
) -> datetime:
    if value is None:
        # A malformed published row must fail closed instead of becoming
        # offline content with an invented timestamp.
        raise EntityNotFoundError(f"Published mobile {entity_name}", entity_id)
    return value


def _scoped_projection_id(
    namespace: uuid.UUID,
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
) -> uuid.UUID:
    return uuid.uuid5(namespace, f"{group_id}:{passenger_id}")
