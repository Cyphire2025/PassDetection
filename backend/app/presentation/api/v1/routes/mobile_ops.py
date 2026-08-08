"""Coordinator operations, push registration, and mobile notification feed."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from collections.abc import Sequence
from contextlib import aclosing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.application.mobile.coordinator_roster_revision import (
    coordinator_roster_revision,
)
from app.application.mobile.sync_journal import append_mobile_sync_change
from app.application.security.mobile_access_policy import MobileAccessPolicy
from app.core.config.settings import get_settings
from app.core.security.mobile_jwt import (
    MobileAccessClaims,
    hash_mobile_lookup,
)
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.domain.entities.entities import OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
from app.domain.exceptions.exceptions import AuthorizationError, EntityNotFoundError
from app.domain.value_objects.travel_document_taxonomy import (
    FLIGHT_TICKET_DOCUMENT_TYPES,
)
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobileIdempotencyReceiptModel,
    MobileIncidentModel,
    MobileNotificationModel,
    MobilePushRegistrationModel,
    MobileSyncChangeModel,
)
from app.infrastructure.database.models import (
    AttendanceRecordModel,
    AttendanceSessionModel,
    DistributedDocumentModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingHotelModel,
    RoomingRoomModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.qr.approved_passenger_qr_issuer import qr_hash
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.mobile_ops_notification_support import (
    _ANNOUNCEMENT_NOTIFICATION_TYPE as _ANNOUNCEMENT_NOTIFICATION_TYPE,
)
from app.presentation.api.v1.routes.mobile_ops_notification_support import (
    _accessible_group_ids,
    _notification_recipient_filter,
    _notification_response,
    _published_announcement_notification_filter,
)
from app.presentation.api.v1.routes.mobile_ops_notification_support import (
    _mobile_priority as _mobile_priority,
)
from app.presentation.api.v1.routes.mobile_ops_notification_support import (
    _safe_public_payload as _safe_public_payload,
)
from app.presentation.api.v1.routes.mobile_ops_passenger_support import (
    _COORDINATOR_DOCUMENT_CATEGORY_ALIASES as _COORDINATOR_DOCUMENT_CATEGORY_ALIASES,
)
from app.presentation.api.v1.routes.mobile_ops_passenger_support import (
    _COORDINATOR_PROJECTED_METADATA_KEYS as _COORDINATOR_PROJECTED_METADATA_KEYS,
)
from app.presentation.api.v1.routes.mobile_ops_passenger_support import (
    _COORDINATOR_SENSITIVE_METADATA_COMPOUNDS as _COORDINATOR_SENSITIVE_METADATA_COMPOUNDS,
)
from app.presentation.api.v1.routes.mobile_ops_passenger_support import (
    _COORDINATOR_SENSITIVE_METADATA_TOKENS as _COORDINATOR_SENSITIVE_METADATA_TOKENS,
)
from app.presentation.api.v1.routes.mobile_ops_passenger_support import (
    _MAX_COORDINATOR_OPERATIONAL_DETAILS as _MAX_COORDINATOR_OPERATIONAL_DETAILS,
)
from app.presentation.api.v1.routes.mobile_ops_passenger_support import (
    _bounded_operational_value as _bounded_operational_value,
)
from app.presentation.api.v1.routes.mobile_ops_passenger_support import (
    _bounded_optional_text,
    _coordinator_document_category,
    _coordinator_metadata_value,
    _coordinator_operational_details,
    _coordinator_reviewed_passport_field,
    _safe_optional_date,
    _validate_manager_document_signature,
)
from app.presentation.api.v1.routes.mobile_ops_passenger_support import (
    _coordinator_metadata_field_is_safe as _coordinator_metadata_field_is_safe,
)
from app.presentation.api.v1.routes.mobile_ops_passenger_support import (
    _coordinator_metadata_label as _coordinator_metadata_label,
)
from app.presentation.api.v1.routes.tour_operations import (
    SCANNABLE_ATTENDANCE_STATUSES,
    _insert_canonical_attendance_record,
    normalize_attendance_activity_name,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileAttendanceActionInput,
    MobileAttendanceActionResult,
    MobileAttendanceBatchRequest,
    MobileAttendanceBatchResponse,
    MobileAttendanceMissingPassengerResponse,
    MobileAttendanceRosterPageResponse,
    MobileAttendanceSessionCreateRequest,
    MobileAttendanceSessionDetailsResponse,
    MobileAttendanceSessionPageResponse,
    MobileAttendanceSessionResponse,
    MobileAttendanceSummaryResponse,
    MobileCoordinatorPassengerDetailResponse,
    MobileCoordinatorPassengerResponse,
    MobileCoordinatorRosterResponse,
    MobileIncidentActionResponse,
    MobileIncidentCreateRequest,
    MobileManagerPassengerResponse,
    MobileManagerRosterResponse,
    MobileNotificationPageResponse,
    MobileNotificationReadResponse,
    MobilePushRegistrationRequest,
    MobilePushRegistrationResponse,
    MobilePushUnregisterRequest,
    MobilePushUnregisterResponse,
)
from app.presentation.dependencies.mobile_auth import require_unrestricted_mobile_claims
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()

_APP_BUNDLE_ID = "com.globalconnects.groupcompanion"
_MAX_ROSTER_PAGE = 200
_MAX_NOTIFICATION_PAGE = 200
_PUSH_ONLY_NOTIFICATION_TYPES = frozenset({"trip_countdown"})
_MAX_ATTENDANCE_SESSION_PAGE = 100
_MAX_MISSING_PASSENGER_PAGE = 200
_MAX_SCAN_CLOCK_SKEW = timedelta(minutes=15)
_IDEMPOTENCY_RECEIPT_TTL = timedelta(days=30)
_MANAGER_PREVIEW_DOCUMENT_TYPES = frozenset({"visa", "flight_ticket"})
_MANAGER_PREVIEW_DATABASE_TYPES = {
    "visa": ("visa",),
    "flight_ticket": (*FLIGHT_TICKET_DOCUMENT_TYPES, "ticket"),
}
_MANAGER_PREVIEW_CONTENT_TYPES = frozenset(
    {"application/pdf", "image/jpeg", "image/png", "image/webp"}
)
_MANAGER_PREVIEW_STREAM_SLOTS = asyncio.Semaphore(16)


@dataclass(frozen=True, slots=True)
class _PreparedAttendanceAction:
    action: MobileAttendanceActionInput
    attendance_session: AttendanceSessionModel
    passenger: PassportSubmissionModel


@dataclass(slots=True)
class _AttendanceReplaySnapshot:
    passengers: set[tuple[uuid.UUID, uuid.UUID]]
    event_passengers: dict[tuple[uuid.UUID, str], set[uuid.UUID]]


@router.get(
    "/coordinator/groups/{group_id}/passengers",
    response_model=MobileCoordinatorRosterResponse,
)
async def list_mobile_coordinator_passengers(
    group_id: uuid.UUID,
    search: str = Query(default="", max_length=120),
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=_MAX_ROSTER_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileCoordinatorRosterResponse:
    trip = await _require_coordinator_trip(session, claims, group_id)
    del trip

    employee_code = func.coalesce(
        PassportSubmissionModel.confirmed_fields["agent_employee_code"].as_string(),
        PassportSubmissionModel.staff_metadata["agent_employee_code"].as_string(),
        PassportSubmissionModel.staff_metadata["employee_code"].as_string(),
    )
    meal_preference = func.coalesce(
        PassportSubmissionModel.confirmed_fields["meal_preference"].as_string(),
        PassportSubmissionModel.staff_metadata["meal_preference"].as_string(),
    )
    room_number = (
        select(RoomingRoomModel.room_number)
        .join(RoomingAssignmentModel, RoomingAssignmentModel.room_id == RoomingRoomModel.id)
        .join(RoomingHotelModel, RoomingHotelModel.id == RoomingAssignmentModel.hotel_id)
        .where(
            RoomingAssignmentModel.passenger_id == PassportSubmissionModel.id,
            RoomingHotelModel.agency_id == claims.agency_id,
            RoomingHotelModel.group_id == group_id,
        )
        .order_by(RoomingHotelModel.check_in_date.desc(), RoomingHotelModel.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    filters = [
        PassportSubmissionModel.agency_id == claims.agency_id,
        PassportSubmissionModel.group_id == group_id,
        PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
    ]
    normalized_search = " ".join(search.split())
    if normalized_search:
        filters.append(
            or_(
                PassportSubmissionModel.client_name.icontains(normalized_search, autoescape=True),
                employee_code.icontains(normalized_search, autoescape=True),
            )
        )
    total = (
        await session.execute(select(func.count(PassportSubmissionModel.id)).where(*filters))
    ).scalar_one()
    if cursor is not None:
        filters.append(PassportSubmissionModel.id > cursor)
    rows = list(
        (
            await session.execute(
                select(
                    PassportSubmissionModel.id,
                    PassportSubmissionModel.client_name,
                    employee_code.label("employee_code"),
                    meal_preference.label("meal_preference"),
                    room_number.label("room_number"),
                )
                .where(*filters)
                .order_by(PassportSubmissionModel.id)
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    attendance_session = await _latest_attendance_session(session, claims, group_id)
    present_ids: set[uuid.UUID] = set()
    if attendance_session is not None and rows:
        present_ids = set(
            (
                await session.execute(
                    select(AttendanceRecordModel.passenger_id).where(
                        AttendanceRecordModel.agency_id == claims.agency_id,
                        AttendanceRecordModel.session_id == attendance_session.id,
                        AttendanceRecordModel.passenger_id.in_([row.id for row in rows]),
                    )
                )
            ).scalars()
        )
    session_completed = attendance_session is not None and attendance_session.status == "completed"
    return MobileCoordinatorRosterResponse(
        items=[
            MobileCoordinatorPassengerResponse(
                id=row.id,
                display_name=row.client_name,
                employee_code=_bounded_optional_text(row.employee_code, 120),
                attendance_status=(
                    "present"
                    if row.id in present_ids
                    else "missing"
                    if session_completed
                    else "not_marked"
                ),
                room_number=_bounded_optional_text(row.room_number, 80),
                meal_preference=_bounded_optional_text(row.meal_preference, 255),
                has_alert=False,
            )
            for row in rows
        ],
        next_cursor=str(rows[-1].id) if has_more and rows else None,
        total=int(total or 0),
    )


@router.get(
    "/manager/groups/{group_id}/passengers",
    response_model=MobileManagerRosterResponse,
)
async def list_mobile_manager_passengers(
    group_id: uuid.UUID,
    search: str = Query(default="", max_length=120),
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=_MAX_ROSTER_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileManagerRosterResponse:
    """Return a bounded, assignment-scoped roster without document bytes."""

    await _require_client_manager_trip(session, claims, group_id)
    employee_code = func.coalesce(
        PassportSubmissionModel.confirmed_fields["agent_employee_code"].as_string(),
        PassportSubmissionModel.staff_metadata["agent_employee_code"].as_string(),
        PassportSubmissionModel.staff_metadata["employee_code"].as_string(),
    )
    filters = [
        PassportSubmissionModel.agency_id == claims.agency_id,
        PassportSubmissionModel.group_id == group_id,
    ]
    normalized_search = " ".join(search.split())
    if normalized_search:
        filters.append(
            or_(
                PassportSubmissionModel.client_name.icontains(normalized_search, autoescape=True),
                employee_code.icontains(normalized_search, autoescape=True),
            )
        )
    total = (
        await session.execute(select(func.count(PassportSubmissionModel.id)).where(*filters))
    ).scalar_one()
    if cursor is not None:
        filters.append(PassportSubmissionModel.id > cursor)
    rows = list(
        (
            await session.execute(
                select(
                    PassportSubmissionModel.id,
                    PassportSubmissionModel.client_name,
                    employee_code.label("employee_code"),
                )
                .where(*filters)
                .order_by(PassportSubmissionModel.id)
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    document_types: dict[uuid.UUID, set[str]] = {}
    if rows:
        for passenger_id, document_type in (
            await session.execute(
                select(
                    DistributedDocumentModel.passenger_id,
                    DistributedDocumentModel.document_type,
                )
                .where(
                    DistributedDocumentModel.agency_id == claims.agency_id,
                    DistributedDocumentModel.group_id == group_id,
                    DistributedDocumentModel.passenger_id.in_([row.id for row in rows]),
                    DistributedDocumentModel.match_status == "matched",
                )
                .distinct()
            )
        ).all():
            document_types.setdefault(passenger_id, set()).add(
                _coordinator_document_category(document_type)
            )
    return MobileManagerRosterResponse(
        items=[
            MobileManagerPassengerResponse(
                id=row.id,
                display_name=row.client_name,
                employee_code=_bounded_optional_text(row.employee_code, 120),
                visa_status=(
                    "available" if "visa" in document_types.get(row.id, set()) else "not_available"
                ),
                flight_ticket_status=(
                    "available"
                    if "flight_ticket" in document_types.get(row.id, set())
                    else "not_available"
                ),
            )
            for row in rows
        ],
        next_cursor=str(rows[-1].id) if has_more and rows else None,
        total=int(total or 0),
    )


@router.get(
    "/coordinator/groups/{group_id}/passengers/{passenger_id}",
    response_model=MobileCoordinatorPassengerDetailResponse,
)
async def get_mobile_coordinator_passenger(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileCoordinatorPassengerDetailResponse:
    """Return one explicit, permission-minimized operational passenger profile."""

    await _require_coordinator_trip(session, claims, group_id)
    return await _mobile_operational_passenger_detail(
        session,
        claims=claims,
        group_id=group_id,
        passenger_id=passenger_id,
    )


@router.get(
    "/manager/groups/{group_id}/passengers/{passenger_id}",
    response_model=MobileCoordinatorPassengerDetailResponse,
)
async def get_mobile_manager_passenger(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileCoordinatorPassengerDetailResponse:
    await _require_client_manager_trip(session, claims, group_id)
    return await _mobile_operational_passenger_detail(
        session,
        claims=claims,
        group_id=group_id,
        passenger_id=passenger_id,
        operationally_approved_only=False,
    )


async def _mobile_operational_passenger_detail(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    operationally_approved_only: bool = True,
) -> MobileCoordinatorPassengerDetailResponse:
    employee_code = func.coalesce(
        PassportSubmissionModel.confirmed_fields["agent_employee_code"].as_string(),
        PassportSubmissionModel.staff_metadata["agent_employee_code"].as_string(),
        PassportSubmissionModel.staff_metadata["employee_code"].as_string(),
    )
    meal_preference = func.coalesce(
        PassportSubmissionModel.confirmed_fields["meal_preference"].as_string(),
        PassportSubmissionModel.staff_metadata["meal_preference"].as_string(),
    )
    employee_type = func.coalesce(
        PassportSubmissionModel.confirmed_fields["agent_employee_type"].as_string(),
        PassportSubmissionModel.staff_metadata["agent_employee_type"].as_string(),
        PassportSubmissionModel.staff_metadata["employee_type"].as_string(),
    )
    designation = func.coalesce(
        PassportSubmissionModel.confirmed_fields["designation"].as_string(),
        PassportSubmissionModel.staff_metadata["designation"].as_string(),
    )
    department = func.coalesce(
        PassportSubmissionModel.confirmed_fields["department"].as_string(),
        PassportSubmissionModel.staff_metadata["department"].as_string(),
    )
    gender = func.coalesce(
        PassportSubmissionModel.confirmed_fields["sex"].as_string(),
        PassportSubmissionModel.confirmed_fields["gender"].as_string(),
        PassportSubmissionModel.staff_metadata["gender"].as_string(),
        PassportSubmissionModel.family_gender,
    )
    date_of_birth = func.coalesce(
        PassportSubmissionModel.confirmed_fields["date_of_birth"].as_string(),
        PassportSubmissionModel.staff_metadata["date_of_birth"].as_string(),
    )
    nationality = func.coalesce(
        PassportSubmissionModel.confirmed_fields["nationality"].as_string(),
        PassportSubmissionModel.extracted_fields["nationality"].as_string(),
        PassportSubmissionModel.staff_metadata["nationality"].as_string(),
    )
    staff_code = func.coalesce(
        PassportSubmissionModel.confirmed_fields["staff_code"].as_string(),
        PassportSubmissionModel.staff_metadata["staff_code"].as_string(),
    )
    base_city = func.coalesce(
        PassportSubmissionModel.confirmed_fields["base_city"].as_string(),
        PassportSubmissionModel.staff_metadata["base_city"].as_string(),
    )
    agency_dealership_name = func.coalesce(
        PassportSubmissionModel.confirmed_fields["agency_dealership_name"].as_string(),
        PassportSubmissionModel.staff_metadata["agency_dealership_name"].as_string(),
    )
    zone_name = func.coalesce(
        PassportSubmissionModel.staff_metadata["zone_name"].as_string(),
        PassportSubmissionModel.staff_metadata["source_zone"].as_string(),
    )
    passport_surname = _coordinator_reviewed_passport_field("surname")
    passport_given_names = _coordinator_reviewed_passport_field("given_names")
    passport_place_of_issue = _coordinator_reviewed_passport_field("place_of_issue")
    passport_issuing_country = _coordinator_reviewed_passport_field("issuing_country")
    passport_date_of_issue = _coordinator_reviewed_passport_field("date_of_issue")
    passport_date_of_expiry = _coordinator_reviewed_passport_field("date_of_expiry")
    passenger_filters = [
        PassportSubmissionModel.id == passenger_id,
        PassportSubmissionModel.agency_id == claims.agency_id,
        PassportSubmissionModel.group_id == group_id,
    ]
    if operationally_approved_only:
        passenger_filters.append(
            PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES)
        )
    row = (
        await session.execute(
            select(
                PassportSubmissionModel.id,
                PassportSubmissionModel.client_name,
                PassportSubmissionModel.client_phone,
                PassportSubmissionModel.client_email,
                PassportSubmissionModel.departure_city,
                PassportSubmissionModel.nearest_domestic_airport,
                PassportSubmissionModel.family_relation,
                PassportSubmissionModel.family_head_name,
                PassportSubmissionModel.family_head_phone,
                PassportSubmissionModel.family_head_email,
                PassportSubmissionModel.submission_mode,
                PassportSubmissionModel.qualifier_relation_label,
                PassportSubmissionModel.status,
                PassportSubmissionModel.staff_metadata,
                PassportSubmissionModel.custom_answers,
                PassportSubmissionModel.custom_detail_answers,
                PassportSubmissionModel.image_s3_key,
                PassportSubmissionModel.updated_at,
                employee_code.label("employee_code"),
                employee_type.label("employee_type"),
                staff_code.label("staff_code"),
                base_city.label("base_city"),
                agency_dealership_name.label("agency_dealership_name"),
                zone_name.label("zone_name"),
                meal_preference.label("meal_preference"),
                designation.label("designation"),
                department.label("department"),
                gender.label("gender"),
                date_of_birth.label("date_of_birth"),
                nationality.label("nationality"),
                passport_surname.label("passport_surname"),
                passport_given_names.label("passport_given_names"),
                passport_place_of_issue.label("passport_place_of_issue"),
                passport_issuing_country.label("passport_issuing_country"),
                passport_date_of_issue.label("passport_date_of_issue"),
                passport_date_of_expiry.label("passport_date_of_expiry"),
            ).where(*passenger_filters)
        )
    ).one_or_none()
    if row is None:
        raise EntityNotFoundError("Coordinator passenger", passenger_id)

    staff_metadata = row.staff_metadata if isinstance(row.staff_metadata, dict) else {}
    emergency_contact_name = _coordinator_metadata_value(
        staff_metadata,
        (
            "emergency_contact_name",
            "emergency_name",
            "emergency_contact_person",
            "emergency_person",
        ),
        max_length=255,
    )
    emergency_contact_phone = _coordinator_metadata_value(
        staff_metadata,
        (
            "emergency_contact_phone",
            "emergency_phone",
            "emergency_contact_number",
            "emergency_mobile",
        ),
        max_length=64,
    )
    emergency_contact_relation = _coordinator_metadata_value(
        staff_metadata,
        ("emergency_contact_relation", "emergency_relation"),
        max_length=120,
    )
    operational_remarks = _coordinator_metadata_value(
        staff_metadata,
        ("remarks", "remark"),
        max_length=2048,
    )
    additional_details = _coordinator_operational_details(
        staff_metadata=staff_metadata,
        custom_answers=row.custom_answers,
        custom_detail_answers=row.custom_detail_answers,
    )

    room = (
        await session.execute(
            select(
                RoomingRoomModel.id.label("room_id"),
                RoomingRoomModel.room_number,
                RoomingHotelModel.hotel_name,
            )
            .join(
                RoomingAssignmentModel,
                RoomingAssignmentModel.room_id == RoomingRoomModel.id,
            )
            .join(RoomingHotelModel, RoomingHotelModel.id == RoomingAssignmentModel.hotel_id)
            .where(
                RoomingAssignmentModel.passenger_id == passenger_id,
                RoomingHotelModel.agency_id == claims.agency_id,
                RoomingHotelModel.group_id == group_id,
            )
            .order_by(RoomingHotelModel.check_in_date.desc(), RoomingHotelModel.id.desc())
            .limit(1)
        )
    ).first()
    roommate_summary: str | None = None
    if room is not None:
        roommate_names = list(
            (
                await session.execute(
                    select(PassportSubmissionModel.client_name)
                    .join(
                        RoomingAssignmentModel,
                        RoomingAssignmentModel.passenger_id == PassportSubmissionModel.id,
                    )
                    .where(
                        PassportSubmissionModel.agency_id == claims.agency_id,
                        PassportSubmissionModel.group_id == group_id,
                        PassportSubmissionModel.id != passenger_id,
                        PassportSubmissionModel.status.in_(
                            OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
                        ),
                        RoomingAssignmentModel.room_id == room.room_id,
                    )
                    .order_by(RoomingAssignmentModel.position, PassportSubmissionModel.id)
                    .limit(12)
                )
            ).scalars()
        )
        roommate_summary = _bounded_optional_text(", ".join(roommate_names), 500)

    document_types = {
        _coordinator_document_category(value)
        for value in (
            await session.execute(
                select(DistributedDocumentModel.document_type)
                .where(
                    DistributedDocumentModel.agency_id == claims.agency_id,
                    DistributedDocumentModel.group_id == group_id,
                    DistributedDocumentModel.passenger_id == passenger_id,
                    DistributedDocumentModel.match_status == "matched",
                )
                .distinct()
                .order_by(DistributedDocumentModel.document_type)
                .limit(64)
            )
        ).scalars()
    }

    attendance_session = await _latest_attendance_session(session, claims, group_id)
    is_present = False
    if attendance_session is not None:
        is_present = bool(
            (
                await session.execute(
                    select(func.count(AttendanceRecordModel.id)).where(
                        AttendanceRecordModel.agency_id == claims.agency_id,
                        AttendanceRecordModel.session_id == attendance_session.id,
                        AttendanceRecordModel.passenger_id == passenger_id,
                    )
                )
            ).scalar_one()
        )
    session_completed = attendance_session is not None and attendance_session.status == "completed"
    return MobileCoordinatorPassengerDetailResponse(
        id=row.id,
        display_name=row.client_name,
        employee_code=_bounded_optional_text(row.employee_code, 120),
        employee_type=_bounded_optional_text(row.employee_type, 120),
        staff_code=_bounded_optional_text(row.staff_code, 120),
        base_city=_bounded_optional_text(row.base_city, 120),
        agency_dealership_name=_bounded_optional_text(row.agency_dealership_name, 200),
        zone_name=_bounded_optional_text(row.zone_name, 120),
        attendance_status=(
            "present" if is_present else "missing" if session_completed else "not_marked"
        ),
        phone_number=_bounded_optional_text(row.client_phone, 32),
        email=_bounded_optional_text(row.client_email, 255),
        departure_city=_bounded_optional_text(row.departure_city, 120),
        nearest_domestic_airport=_bounded_optional_text(row.nearest_domestic_airport, 120),
        designation=_bounded_optional_text(row.designation, 160),
        department=_bounded_optional_text(row.department, 160),
        gender=_bounded_optional_text(row.gender, 40),
        date_of_birth=_safe_optional_date(row.date_of_birth),
        nationality=_bounded_optional_text(row.nationality, 80),
        passport_surname=_bounded_optional_text(row.passport_surname, 160),
        passport_given_names=_bounded_optional_text(row.passport_given_names, 255),
        passport_place_of_issue=_bounded_optional_text(row.passport_place_of_issue, 160),
        passport_issuing_country=_bounded_optional_text(row.passport_issuing_country, 120),
        passport_date_of_issue=_safe_optional_date(row.passport_date_of_issue),
        passport_date_of_expiry=_safe_optional_date(row.passport_date_of_expiry),
        hotel_name=(_bounded_optional_text(room.hotel_name, 255) if room is not None else None),
        room_number=(_bounded_optional_text(room.room_number, 80) if room is not None else None),
        roommate_summary=roommate_summary,
        meal_preference=_bounded_optional_text(row.meal_preference, 255),
        family_relation=_bounded_optional_text(row.family_relation, 80),
        family_head_name=_bounded_optional_text(row.family_head_name, 255),
        family_head_phone=_bounded_optional_text(row.family_head_phone, 32),
        family_head_email=_bounded_optional_text(row.family_head_email, 255),
        qualifier_relation=_bounded_optional_text(row.qualifier_relation_label, 80),
        emergency_contact_name=emergency_contact_name,
        emergency_contact_phone=emergency_contact_phone,
        emergency_contact_relation=emergency_contact_relation,
        operational_remarks=operational_remarks,
        submission_mode=("family" if row.submission_mode == "family" else "single"),
        submission_status=_bounded_optional_text(row.status, 40) or "unavailable",
        passport_status=(
            "available"
            if row.image_s3_key and not row.image_s3_key.endswith(".placeholder")
            else "not_available"
        ),
        visa_status="available" if "visa" in document_types else "not_available",
        flight_ticket_status=(
            "available" if "flight_ticket" in document_types else "not_available"
        ),
        insurance_status=("available" if "insurance" in document_types else "not_available"),
        hotel_voucher_status=(
            "available" if "hotel_voucher" in document_types else "not_available"
        ),
        other_document_status=("available" if "other" in document_types else "not_available"),
        additional_details=additional_details,
        updated_at=row.updated_at,
        has_alert=False,
    )


@router.get(
    "/manager/groups/{group_id}/passengers/{passenger_id}/documents/{document_type}/preview",
    response_class=StreamingResponse,
)
async def preview_mobile_manager_passenger_document(
    group_id: uuid.UUID,
    passenger_id: uuid.UUID,
    document_type: Literal["visa", "flight_ticket"],
    request: Request,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    """Stream one assigned passenger document without creating an offline grant."""

    await _require_client_manager_trip(session, claims, group_id)
    passenger_exists = (
        await session.execute(
            select(PassportSubmissionModel.id).where(
                PassportSubmissionModel.id == passenger_id,
                PassportSubmissionModel.agency_id == claims.agency_id,
                PassportSubmissionModel.group_id == group_id,
            )
        )
    ).scalar_one_or_none()
    if passenger_exists is None:
        raise EntityNotFoundError("Client manager passenger", passenger_id)
    document = (
        await session.execute(
            select(DistributedDocumentModel)
            .where(
                DistributedDocumentModel.agency_id == claims.agency_id,
                DistributedDocumentModel.group_id == group_id,
                DistributedDocumentModel.passenger_id == passenger_id,
                DistributedDocumentModel.match_status == "matched",
                func.lower(DistributedDocumentModel.document_type).in_(
                    _MANAGER_PREVIEW_DATABASE_TYPES[document_type]
                ),
            )
            .order_by(
                DistributedDocumentModel.updated_at.desc(),
                DistributedDocumentModel.id.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if document is None:
        raise EntityNotFoundError(document_type.replace("_", " ").title(), passenger_id)
    content_type = document.content_type.casefold().split(";", 1)[0].strip()
    if (
        document_type not in _MANAGER_PREVIEW_DOCUMENT_TYPES
        or content_type not in _MANAGER_PREVIEW_CONTENT_TYPES
    ):
        raise AuthorizationError("The requested document cannot be previewed")

    storage = MinioStorageRepository()
    metadata = await storage.stat_file(document.storage_key)
    maximum_size = get_settings().mobile.personal_document_max_bytes
    if metadata.size_bytes < 1 or metadata.size_bytes > maximum_size:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Document is outside the mobile preview limit",
        )
    if metadata.content_type and metadata.content_type != content_type:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document metadata changed; publish the file again",
        )
    signature = await storage.get_file_range(
        document.storage_key,
        start=0,
        end=min(metadata.size_bytes, 16) - 1,
    )
    _validate_manager_document_signature(signature, content_type)
    await AuditLogRepository(session).record(
        action="mobile.client_manager_document_previewed",
        entity_type="distributed_document",
        agency_id=claims.agency_id,
        user_id=claims.principal_id,
        entity_id=str(document.id),
        ip_address=trusted_client_ip(request),
        metadata={
            "group_id": str(group_id),
            "passenger_id": str(passenger_id),
            "document_type": document_type,
        },
    )
    storage_key = document.storage_key
    safe_filename = f"{document_type}.{'pdf' if content_type == 'application/pdf' else content_type.split('/')[-1]}"
    size_bytes = metadata.size_bytes
    await session.commit()
    await session.close()

    async def chunks():  # type: ignore[no-untyped-def]
        async with _MANAGER_PREVIEW_STREAM_SLOTS:
            async with aclosing(
                storage.stream_file(storage_key, start=0, expected_bytes=size_bytes)
            ) as object_stream:
                async for chunk in object_stream:
                    yield chunk

    return StreamingResponse(
        chunks(),
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(safe_filename, safe='')}",
            "Content-Length": str(size_bytes),
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/coordinator/groups/{group_id}/attendance/sessions",
    response_model=MobileAttendanceSessionPageResponse,
)
async def list_mobile_attendance_sessions(
    group_id: uuid.UUID,
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=_MAX_ATTENDANCE_SESSION_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceSessionPageResponse:
    await _require_coordinator_trip(session, claims, group_id)
    return await _list_mobile_attendance_sessions(
        session,
        claims=claims,
        group_id=group_id,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/manager/groups/{group_id}/attendance/sessions",
    response_model=MobileAttendanceSessionPageResponse,
)
async def list_mobile_manager_attendance_sessions(
    group_id: uuid.UUID,
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=_MAX_ATTENDANCE_SESSION_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceSessionPageResponse:
    await _require_client_manager_trip(session, claims, group_id)
    return await _list_mobile_attendance_sessions(
        session,
        claims=claims,
        group_id=group_id,
        cursor=cursor,
        limit=limit,
    )


async def _list_mobile_attendance_sessions(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    cursor: uuid.UUID | None,
    limit: int,
) -> MobileAttendanceSessionPageResponse:
    statement = select(AttendanceSessionModel).where(
        AttendanceSessionModel.agency_id == claims.agency_id,
        AttendanceSessionModel.group_id == group_id,
        AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
    )
    if cursor is not None:
        statement = statement.where(AttendanceSessionModel.id < cursor)
    rows = list(
        (
            await session.execute(
                statement.order_by(AttendanceSessionModel.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = await _mobile_attendance_session_responses(
        session,
        claims=claims,
        group_id=group_id,
        attendance_sessions=rows,
    )
    return MobileAttendanceSessionPageResponse(
        items=items,
        next_cursor=str(rows[-1].id) if has_more and rows else None,
    )


@router.post(
    "/coordinator/groups/{group_id}/attendance/sessions",
    response_model=MobileAttendanceSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_mobile_attendance_session(
    group_id: uuid.UUID,
    body: MobileAttendanceSessionCreateRequest,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceSessionResponse:
    await _require_coordinator_trip(session, claims, group_id)
    display_name = " ".join(body.name.split())
    normalized_name = normalize_attendance_activity_name(display_name)
    now = datetime.now(tz=UTC)
    candidate_id = uuid.uuid4()
    inserted_id = (
        await session.execute(
            pg_insert(AttendanceSessionModel)
            .values(
                id=candidate_id,
                agency_id=claims.agency_id,
                group_id=group_id,
                name=display_name,
                normalized_name=normalized_name,
                canonical_session_id=candidate_id,
                status="active",
                created_by_user_id=claims.principal_id,
                created_at=now,
                updated_at=now,
                started_at=now,
            )
            .on_conflict_do_nothing()
            .returning(AttendanceSessionModel.id)
        )
    ).scalar_one_or_none()
    attendance_session = (
        await session.execute(
            select(AttendanceSessionModel).where(
                AttendanceSessionModel.id == inserted_id
                if inserted_id is not None
                else (
                    (AttendanceSessionModel.agency_id == claims.agency_id)
                    & (AttendanceSessionModel.group_id == group_id)
                    & (AttendanceSessionModel.normalized_name == normalized_name)
                    & AttendanceSessionModel.status.in_(("draft", "active"))
                    & (AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id)
                )
            )
        )
    ).scalar_one_or_none()
    if attendance_session is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attendance activity changed; synchronize and retry",
        )
    if attendance_session.status == "draft":
        attendance_session.status = "active"
        attendance_session.started_at = attendance_session.started_at or now
        attendance_session.updated_at = now
        await session.flush()
    return (
        await _mobile_attendance_session_responses(
            session,
            claims=claims,
            group_id=group_id,
            attendance_sessions=[attendance_session],
        )
    )[0]


@router.get(
    "/coordinator/groups/{group_id}/attendance/sessions/{session_id}",
    response_model=MobileAttendanceSessionDetailsResponse,
)
async def get_mobile_attendance_session_details(
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=_MAX_MISSING_PASSENGER_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceSessionDetailsResponse:
    await _require_coordinator_trip(session, claims, group_id)
    attendance_session = await _mobile_attendance_session(
        session,
        claims=claims,
        group_id=group_id,
        session_id=session_id,
        lock=False,
    )
    scanned_passengers = select(AttendanceRecordModel.passenger_id).where(
        AttendanceRecordModel.agency_id == claims.agency_id,
        AttendanceRecordModel.session_id == attendance_session.id,
    )
    filters = [
        PassportSubmissionModel.agency_id == claims.agency_id,
        PassportSubmissionModel.group_id == group_id,
        PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
        PassportSubmissionModel.id.not_in(scanned_passengers),
    ]
    if cursor is not None:
        filters.append(PassportSubmissionModel.id > cursor)
    missing_rows = list(
        (
            await session.execute(
                select(
                    PassportSubmissionModel.id,
                    PassportSubmissionModel.client_name,
                )
                .where(*filters)
                .order_by(PassportSubmissionModel.id)
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(missing_rows) > limit
    missing_rows = missing_rows[:limit]
    summary = (
        await _mobile_attendance_session_responses(
            session,
            claims=claims,
            group_id=group_id,
            attendance_sessions=[attendance_session],
        )
    )[0]
    return MobileAttendanceSessionDetailsResponse(
        session=summary,
        missing=[
            MobileAttendanceMissingPassengerResponse(
                id=row.id,
                display_name=row.client_name,
            )
            for row in missing_rows
        ],
        next_cursor=(str(missing_rows[-1].id) if has_more and missing_rows else None),
    )


@router.get(
    "/coordinator/groups/{group_id}/attendance/sessions/{session_id}/roster",
    response_model=MobileAttendanceRosterPageResponse,
)
async def list_mobile_coordinator_attendance_roster(
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    roster_status: Literal["counted", "missing"] = Query(alias="status"),
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=_MAX_MISSING_PASSENGER_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceRosterPageResponse:
    await _require_coordinator_trip(session, claims, group_id)
    return await _list_mobile_attendance_roster(
        session,
        claims=claims,
        group_id=group_id,
        session_id=session_id,
        roster_status=roster_status,
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/manager/groups/{group_id}/attendance/sessions/{session_id}/roster",
    response_model=MobileAttendanceRosterPageResponse,
)
async def list_mobile_manager_attendance_roster(
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    roster_status: Literal["counted", "missing"] = Query(alias="status"),
    cursor: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=_MAX_MISSING_PASSENGER_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceRosterPageResponse:
    await _require_client_manager_trip(session, claims, group_id)
    return await _list_mobile_attendance_roster(
        session,
        claims=claims,
        group_id=group_id,
        session_id=session_id,
        roster_status=roster_status,
        cursor=cursor,
        limit=limit,
    )


async def _list_mobile_attendance_roster(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    roster_status: Literal["counted", "missing"],
    cursor: uuid.UUID | None,
    limit: int,
) -> MobileAttendanceRosterPageResponse:
    attendance_session = await _mobile_attendance_session(
        session,
        claims=claims,
        group_id=group_id,
        session_id=session_id,
        lock=False,
    )
    scanned_passengers = select(AttendanceRecordModel.passenger_id).where(
        AttendanceRecordModel.agency_id == claims.agency_id,
        AttendanceRecordModel.session_id == attendance_session.id,
    )
    filters = [
        PassportSubmissionModel.agency_id == claims.agency_id,
        PassportSubmissionModel.group_id == group_id,
        PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
        (
            PassportSubmissionModel.id.in_(scanned_passengers)
            if roster_status == "counted"
            else PassportSubmissionModel.id.not_in(scanned_passengers)
        ),
    ]
    if cursor is not None:
        filters.append(PassportSubmissionModel.id > cursor)
    rows = list(
        (
            await session.execute(
                select(PassportSubmissionModel.id, PassportSubmissionModel.client_name)
                .where(*filters)
                .order_by(PassportSubmissionModel.id)
                .limit(limit + 1)
            )
        ).all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    summary = (
        await _mobile_attendance_session_responses(
            session,
            claims=claims,
            group_id=group_id,
            attendance_sessions=[attendance_session],
        )
    )[0]
    return MobileAttendanceRosterPageResponse(
        session=summary,
        items=[
            MobileAttendanceMissingPassengerResponse(
                id=row.id,
                display_name=row.client_name,
            )
            for row in rows
        ],
        next_cursor=str(rows[-1].id) if has_more and rows else None,
    )


@router.put(
    "/coordinator/groups/{group_id}/attendance/sessions/{session_id}/complete",
    response_model=MobileAttendanceSessionResponse,
)
async def complete_mobile_attendance_session(
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceSessionResponse:
    await _require_coordinator_trip(session, claims, group_id)
    attendance_session = await _mobile_attendance_session(
        session,
        claims=claims,
        group_id=group_id,
        session_id=session_id,
        lock=True,
    )
    if attendance_session.status != "completed":
        now = datetime.now(tz=UTC)
        attendance_session.status = "completed"
        attendance_session.completed_at = now
        attendance_session.updated_at = now
        await session.flush()
    return (
        await _mobile_attendance_session_responses(
            session,
            claims=claims,
            group_id=group_id,
            attendance_sessions=[attendance_session],
        )
    )[0]


@router.post(
    "/coordinator/groups/{group_id}/attendance/actions",
    response_model=MobileAttendanceBatchResponse,
)
async def apply_mobile_attendance_actions(
    group_id: uuid.UUID,
    body: MobileAttendanceBatchRequest,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceBatchResponse:
    trip = await _require_coordinator_trip(session, claims, group_id)
    now = datetime.now(tz=UTC)
    resolved_results: dict[int, MobileAttendanceActionResult] = {}
    session_candidates: list[tuple[int, MobileAttendanceActionInput]] = []
    for index, action in enumerate(body.actions):
        if action.scanned_at > now + _MAX_SCAN_CLOCK_SKEW:
            resolved_results[index] = MobileAttendanceActionResult(
                client_event_id=action.client_event_id,
                status="rejected",
                reason_code="SCANNED_AT_IN_FUTURE",
            )
        else:
            session_candidates.append((index, action))

    attendance_sessions = await _attendance_sessions_for_actions(
        session,
        claims,
        group_id,
        actions=[action for _, action in session_candidates],
    )
    qr_candidates: list[
        tuple[int, MobileAttendanceActionInput, AttendanceSessionModel]
    ] = []
    for index, action in session_candidates:
        attendance_session = attendance_sessions.get(action.session_id)
        if attendance_session is None:
            resolved_results[index] = MobileAttendanceActionResult(
                client_event_id=action.client_event_id,
                status="refresh_required",
                reason_code="ATTENDANCE_SESSION_SELECTION_REQUIRED",
            )
            continue
        if (
            attendance_session.started_at is not None
            and action.scanned_at < attendance_session.started_at - _MAX_SCAN_CLOCK_SKEW
        ) or (
            attendance_session.completed_at is not None
            and action.scanned_at > attendance_session.completed_at + _MAX_SCAN_CLOCK_SKEW
        ):
            resolved_results[index] = MobileAttendanceActionResult(
                client_event_id=action.client_event_id,
                status="rejected",
                reason_code="SCANNED_OUTSIDE_SESSION_WINDOW",
            )
            continue
        qr_candidates.append((index, action, attendance_session))

    qr_snapshot = await _scannable_passenger_snapshot(
        session,
        claims=claims,
        actions=[action for _, action, _ in qr_candidates],
    )
    prepared_by_index: dict[int, _PreparedAttendanceAction] = {}
    for index, action, attendance_session in qr_candidates:
        passenger, rejection_reason = _resolve_scannable_passenger_from_snapshot(
            qr_snapshot,
            group_id=group_id,
            qr_payload=action.signed_qr,
        )
        if passenger is None:
            resolved_results[index] = MobileAttendanceActionResult(
                client_event_id=action.client_event_id,
                status="rejected",
                reason_code=_attendance_rejection_code(rejection_reason),
            )
            continue
        prepared_by_index[index] = _PreparedAttendanceAction(
            action=action,
            attendance_session=attendance_session,
            passenger=passenger,
        )

    replay_snapshot = await _attendance_replay_snapshot(
        session,
        claims=claims,
        prepared=list(prepared_by_index.values()),
    )
    results: list[MobileAttendanceActionResult] = []
    accepted_roster_changes: list[
        tuple[PassportSubmissionModel, datetime]
    ] = []
    for index, action in enumerate(body.actions):
        resolved_result = resolved_results.get(index)
        if resolved_result is not None:
            results.append(resolved_result)
            continue
        prepared = prepared_by_index[index]
        replay_state = _attendance_replay_state_from_snapshot(
            replay_snapshot,
            attendance_session=prepared.attendance_session,
            passenger_id=prepared.passenger.id,
            client_event_id=str(action.client_event_id),
        )
        if replay_state == "event_reused":
            results.append(
                MobileAttendanceActionResult(
                    client_event_id=action.client_event_id,
                    status="rejected",
                    reason_code="IDEMPOTENCY_KEY_REUSED",
                )
            )
            continue
        if replay_state == "already_applied":
            results.append(
                MobileAttendanceActionResult(
                    client_event_id=action.client_event_id,
                    status="already_applied",
                    server_version=None,
                    reason_code=None,
                )
            )
            continue
        inserted_id = await _insert_canonical_attendance_record(
            session=session,
            agency_id=claims.agency_id,
            attendance_session=prepared.attendance_session,
            passenger_id=prepared.passenger.id,
            coordinator_user_id=claims.principal_id,
            scanned_at=action.scanned_at.astimezone(UTC),
            sync_source="offline",
            client_event_id=str(action.client_event_id),
            device_id=str(claims.session_id),
        )
        if inserted_id is None:
            replay_state = await _attendance_replay_state(
                session,
                claims=claims,
                attendance_session=prepared.attendance_session,
                passenger_id=prepared.passenger.id,
                client_event_id=str(action.client_event_id),
            )
            if replay_state == "event_reused":
                results.append(
                    MobileAttendanceActionResult(
                        client_event_id=action.client_event_id,
                        status="rejected",
                        reason_code="IDEMPOTENCY_KEY_REUSED",
                    )
                )
                continue
            if replay_state == "unknown":
                results.append(
                    MobileAttendanceActionResult(
                        client_event_id=action.client_event_id,
                        status="refresh_required",
                        reason_code="ATTENDANCE_CONFLICT",
                    )
                )
                continue
            _record_attendance_replay(
                replay_snapshot,
                attendance_session=prepared.attendance_session,
                passenger_id=prepared.passenger.id,
                client_event_id=str(action.client_event_id),
            )
        else:
            changed_at = datetime.now(tz=UTC)
            prepared.attendance_session.updated_at = changed_at
            accepted_roster_changes.append((prepared.passenger, changed_at))
            _record_attendance_replay(
                replay_snapshot,
                attendance_session=prepared.attendance_session,
                passenger_id=prepared.passenger.id,
                client_event_id=str(action.client_event_id),
            )
        results.append(
            MobileAttendanceActionResult(
                client_event_id=action.client_event_id,
                status="accepted" if inserted_id is not None else "already_applied",
                server_version=None,
                reason_code=None,
            )
        )

    targeted_roster_changes: list[MobileSyncChangeModel] = []
    for passenger, changed_at in accepted_roster_changes:
        targeted_roster_changes.append(
            await append_mobile_sync_change(
                session,
                access=trip.access,
                audience="coordinator",
                entity_type="coordinator_passenger",
                entity_id=passenger.id,
                operation="upsert",
                version=max(0, int(changed_at.timestamp() * 1000)),
                changed_by_user_id=claims.principal_id,
                payload={
                    "resource_path": (
                        f"/api/v1/mobile/coordinator/groups/{group_id}/"
                        f"passengers/{passenger.id}"
                    )
                },
                flush=False,
            )
        )
    if targeted_roster_changes:
        # Flush the bounded journal batch once before deriving its proof. The
        # conflict-safe attendance inserts above remain ordered one by one.
        await session.flush()
        roster_revision = await coordinator_roster_revision(
            session,
            agency_id=claims.agency_id,
            group_id=group_id,
        )
        for change in targeted_roster_changes:
            change.payload = {**change.payload, "roster_revision": roster_revision}
        await session.flush()
    return MobileAttendanceBatchResponse(results=results)


async def _attendance_replay_state(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    attendance_session: AttendanceSessionModel,
    passenger_id: uuid.UUID,
    client_event_id: str,
) -> str:
    """Distinguish a safe retry from a reused offline idempotency key."""

    family_session = aliased(
        AttendanceSessionModel,
        name="mobile_attendance_session_family",
    )
    rows = list(
        (
            await session.execute(
                select(
                    AttendanceRecordModel.passenger_id,
                    AttendanceRecordModel.client_event_id,
                )
                .join(
                    family_session,
                    family_session.id == AttendanceRecordModel.session_id,
                )
                .where(
                    AttendanceRecordModel.agency_id == claims.agency_id,
                    family_session.canonical_session_id == attendance_session.id,
                    or_(
                        AttendanceRecordModel.passenger_id == passenger_id,
                        AttendanceRecordModel.client_event_id == client_event_id,
                    ),
                )
                .limit(2)
            )
        ).all()
    )
    if any(
        row.client_event_id == client_event_id and row.passenger_id != passenger_id for row in rows
    ):
        return "event_reused"
    if rows:
        return "already_applied"
    return "unknown"


async def _attendance_sessions_for_actions(
    session: AsyncSession,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    *,
    actions: Sequence[MobileAttendanceActionInput],
) -> dict[uuid.UUID | None, AttendanceSessionModel | None]:
    """Resolve a bounded attendance batch with at most two scoped reads."""

    if not actions:
        return {}
    statement = select(AttendanceSessionModel).where(
        AttendanceSessionModel.agency_id == claims.agency_id,
        AttendanceSessionModel.group_id == group_id,
        AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
        AttendanceSessionModel.status.in_(SCANNABLE_ATTENDANCE_STATUSES),
    )
    resolved: dict[uuid.UUID | None, AttendanceSessionModel | None] = {}
    requested_ids = {action.session_id for action in actions if action.session_id is not None}
    if requested_ids:
        rows = list(
            (
                await session.execute(
                    statement.where(AttendanceSessionModel.id.in_(requested_ids))
                )
            ).scalars()
        )
        resolved.update({requested_id: None for requested_id in requested_ids})
        resolved.update({item.id: item for item in rows})
    if any(action.session_id is None for action in actions):
        candidates = list(
            (
                await session.execute(
                    statement.order_by(AttendanceSessionModel.updated_at.desc()).limit(2)
                )
            ).scalars()
        )
        resolved[None] = candidates[0] if len(candidates) == 1 else None
    return resolved


async def _scannable_passenger_snapshot(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    actions: Sequence[MobileAttendanceActionInput],
) -> dict[str, tuple[PassportSubmissionModel, PassengerQRTokenModel]]:
    """Load all QR targets for one validated, schema-bounded batch."""

    token_hashes = {qr_hash(action.signed_qr.strip()) for action in actions}
    if not token_hashes:
        return {}
    rows = list(
        (
            await session.execute(
                select(PassportSubmissionModel, PassengerQRTokenModel)
                .join(
                    PassengerQRTokenModel,
                    PassengerQRTokenModel.passenger_id == PassportSubmissionModel.id,
                )
                .where(
                    PassengerQRTokenModel.agency_id == claims.agency_id,
                    PassportSubmissionModel.agency_id == claims.agency_id,
                    PassengerQRTokenModel.token_hash.in_(token_hashes),
                    PassportSubmissionModel.status.in_(
                        OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
                    ),
                )
            )
        ).all()
    )
    return {token.token_hash: (passenger, token) for passenger, token in rows}


def _resolve_scannable_passenger_from_snapshot(
    snapshot: dict[str, tuple[PassportSubmissionModel, PassengerQRTokenModel]],
    *,
    group_id: uuid.UUID,
    qr_payload: str,
) -> tuple[PassportSubmissionModel | None, str | None]:
    """Apply the existing fail-closed QR rejection precedence in memory."""

    resolved = snapshot.get(qr_hash(qr_payload.strip()))
    if resolved is None:
        return None, "unknown_token"
    passenger, token = resolved
    if token.revoked_at is not None:
        return None, "revoked"
    if token.expires_at <= datetime.now(tz=UTC):
        return None, "expired"
    if not token.is_active:
        return None, "inactive"
    if passenger.group_id != group_id:
        return None, "wrong_group"
    return passenger, None


async def _attendance_replay_snapshot(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    prepared: Sequence[_PreparedAttendanceAction],
) -> _AttendanceReplaySnapshot:
    """Preload known canonical-family retries without weakening insert races."""

    snapshot = _AttendanceReplaySnapshot(passengers=set(), event_passengers={})
    if not prepared:
        return snapshot
    passenger_pairs = sorted(
        {
            (item.attendance_session.id, item.passenger.id)
            for item in prepared
        },
        key=lambda pair: (str(pair[0]), str(pair[1])),
    )
    event_pairs = sorted(
        {
            (item.attendance_session.id, str(item.action.client_event_id))
            for item in prepared
        },
        key=lambda pair: (str(pair[0]), pair[1]),
    )
    family_session = aliased(
        AttendanceSessionModel,
        name="mobile_attendance_batch_session_family",
    )
    rows = list(
        (
            await session.execute(
                select(
                    family_session.canonical_session_id.label("canonical_session_id"),
                    AttendanceRecordModel.passenger_id,
                    AttendanceRecordModel.client_event_id,
                )
                .join(
                    family_session,
                    family_session.id == AttendanceRecordModel.session_id,
                )
                .where(
                    AttendanceRecordModel.agency_id == claims.agency_id,
                    family_session.agency_id == claims.agency_id,
                    or_(
                        tuple_(
                            family_session.canonical_session_id,
                            AttendanceRecordModel.passenger_id,
                        ).in_(passenger_pairs),
                        tuple_(
                            family_session.canonical_session_id,
                            AttendanceRecordModel.client_event_id,
                        ).in_(event_pairs),
                    ),
                )
            )
        ).all()
    )
    for row in rows:
        session_id = row.canonical_session_id
        snapshot.passengers.add((session_id, row.passenger_id))
        snapshot.event_passengers.setdefault(
            (session_id, row.client_event_id),
            set(),
        ).add(row.passenger_id)
    return snapshot


def _attendance_replay_state_from_snapshot(
    snapshot: _AttendanceReplaySnapshot,
    *,
    attendance_session: AttendanceSessionModel,
    passenger_id: uuid.UUID,
    client_event_id: str,
) -> str:
    event_passengers = snapshot.event_passengers.get(
        (attendance_session.id, client_event_id),
        set(),
    )
    if any(value != passenger_id for value in event_passengers):
        return "event_reused"
    if (
        attendance_session.id,
        passenger_id,
    ) in snapshot.passengers or passenger_id in event_passengers:
        return "already_applied"
    return "unknown"


def _record_attendance_replay(
    snapshot: _AttendanceReplaySnapshot,
    *,
    attendance_session: AttendanceSessionModel,
    passenger_id: uuid.UUID,
    client_event_id: str,
) -> None:
    key = (attendance_session.id, client_event_id)
    snapshot.passengers.add((attendance_session.id, passenger_id))
    snapshot.event_passengers.setdefault(key, set()).add(passenger_id)


@router.get(
    "/coordinator/groups/{group_id}/attendance/summary",
    response_model=MobileAttendanceSummaryResponse,
)
async def get_mobile_attendance_summary(
    group_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileAttendanceSummaryResponse:
    trip = await _require_coordinator_trip(session, claims, group_id)
    attendance_session = await _latest_attendance_session(session, claims, group_id)
    total = (
        await session.execute(
            select(func.count(PassportSubmissionModel.id)).where(
                PassportSubmissionModel.agency_id == claims.agency_id,
                PassportSubmissionModel.group_id == group_id,
                PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
            )
        )
    ).scalar_one()
    present = 0
    updated_at = trip.access.updated_at
    if attendance_session is not None:
        present = int(
            (
                await session.execute(
                    select(func.count(AttendanceRecordModel.id)).where(
                        AttendanceRecordModel.agency_id == claims.agency_id,
                        AttendanceRecordModel.session_id == attendance_session.id,
                    )
                )
            ).scalar_one()
            or 0
        )
        updated_at = attendance_session.updated_at
    total_count = int(total or 0)
    unmarked = max(0, total_count - present)
    completed = attendance_session is not None and attendance_session.status == "completed"
    return MobileAttendanceSummaryResponse(
        trip_id=group_id,
        total=total_count,
        present=present,
        missing=unmarked if completed else 0,
        excused=0,
        not_marked=0 if completed else unmarked,
        version=max(0, int(updated_at.timestamp() * 1000)),
        updated_at=updated_at,
    )


@router.post(
    "/coordinator/groups/{group_id}/incidents",
    response_model=MobileIncidentActionResponse,
)
async def create_mobile_incident(
    group_id: uuid.UUID,
    body: MobileIncidentCreateRequest,
    request: Request,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileIncidentActionResponse:
    trip = await _require_coordinator_trip(session, claims, group_id)
    now = datetime.now(tz=UTC)
    occurred_at = body.occurred_at.astimezone(UTC)
    if occurred_at > now + _MAX_SCAN_CLOCK_SKEW:
        return MobileIncidentActionResponse(
            client_event_id=body.client_event_id,
            status="rejected",
            reason_code="OCCURRED_AT_IN_FUTURE",
        )

    request_payload = body.model_dump(mode="json")
    request_hash = hashlib.sha256(
        json.dumps(
            request_payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    idempotency_key = str(body.client_event_id)
    receipt_id = uuid.uuid4()
    inserted_receipt_id = (
        await session.execute(
            pg_insert(MobileIdempotencyReceiptModel)
            .values(
                id=receipt_id,
                agency_id=claims.agency_id,
                session_id=claims.session_id,
                group_id=group_id,
                gc_group_access_id=trip.access.id,
                idempotency_key=idempotency_key,
                operation="incident.create",
                request_hash=request_hash,
                status="processing",
                response_payload={},
                created_at=now,
                expires_at=now + _IDEMPOTENCY_RECEIPT_TTL,
            )
            .on_conflict_do_nothing(index_elements=["session_id", "idempotency_key"])
            .returning(MobileIdempotencyReceiptModel.id)
        )
    ).scalar_one_or_none()
    receipt_lookup = select(MobileIdempotencyReceiptModel)
    if inserted_receipt_id is not None:
        receipt_lookup = receipt_lookup.where(
            MobileIdempotencyReceiptModel.id == inserted_receipt_id
        )
    else:
        receipt_lookup = receipt_lookup.where(
            MobileIdempotencyReceiptModel.agency_id == claims.agency_id,
            MobileIdempotencyReceiptModel.session_id == claims.session_id,
            MobileIdempotencyReceiptModel.idempotency_key == idempotency_key,
        )
    receipt = (await session.execute(receipt_lookup.with_for_update())).scalar_one_or_none()
    if receipt is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Incident receipt changed; retry with the same event identifier",
        )
    if not hmac.compare_digest(receipt.request_hash, request_hash):
        return MobileIncidentActionResponse(
            client_event_id=body.client_event_id,
            status="rejected",
            reason_code="IDEMPOTENCY_KEY_REUSED",
        )
    if receipt.status == "completed" and receipt.resource_id is not None:
        return MobileIncidentActionResponse(
            client_event_id=body.client_event_id,
            status="already_applied",
            incident_id=receipt.resource_id,
        )

    incident = (
        await session.execute(
            select(MobileIncidentModel).where(
                MobileIncidentModel.agency_id == claims.agency_id,
                MobileIncidentModel.group_id == group_id,
                MobileIncidentModel.gc_group_access_id == trip.access.id,
                MobileIncidentModel.created_by_session_id == claims.session_id,
                MobileIncidentModel.client_event_id == idempotency_key,
            )
        )
    ).scalar_one_or_none()
    created = incident is None
    if incident is None:
        incident = MobileIncidentModel(
            id=uuid.uuid4(),
            agency_id=claims.agency_id,
            group_id=group_id,
            gc_group_access_id=trip.access.id,
            created_by_session_id=claims.session_id,
            reported_by_user_id=claims.principal_id,
            affected_passenger_identity_id=None,
            client_event_id=idempotency_key,
            incident_type="other",
            severity=body.severity,
            status="open",
            title=body.title,
            description=body.description,
            location_text=None,
            is_confidential=True,
            occurred_at=occurred_at,
            created_offline_at=(occurred_at if occurred_at < now - timedelta(minutes=1) else None),
            acknowledged_at=None,
            resolved_at=None,
            resolved_by_user_id=None,
            resolution_note=None,
            created_at=now,
            updated_at=now,
        )
        session.add(incident)
        await session.flush()
        await append_mobile_sync_change(
            session,
            access=trip.access,
            audience="coordinator",
            entity_type="incident",
            entity_id=incident.id,
            operation="upsert",
            version=trip.access.manifest_version,
            changed_by_user_id=claims.principal_id,
            payload={"resource_path": f"/api/v1/mobile/coordinator/groups/{group_id}/incidents"},
        )
        await AuditLogRepository(session).record(
            action="mobile.incident_created",
            entity_type="mobile_incident",
            agency_id=claims.agency_id,
            user_id=claims.principal_id,
            entity_id=str(incident.id),
            ip_address=trusted_client_ip(request),
            metadata={
                "group_id": str(group_id),
                "severity": body.severity,
                "created_offline": incident.created_offline_at is not None,
            },
        )

    response_payload = {
        "client_event_id": idempotency_key,
        "status": "accepted" if created else "already_applied",
        "incident_id": str(incident.id),
        "reason_code": None,
    }
    receipt.status = "completed"
    receipt.response_status_code = status.HTTP_200_OK
    receipt.response_payload = response_payload
    receipt.response_hash = hashlib.sha256(
        json.dumps(response_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    receipt.resource_type = "mobile_incident"
    receipt.resource_id = incident.id
    receipt.completed_at = now
    return MobileIncidentActionResponse(
        client_event_id=body.client_event_id,
        status="accepted" if created else "already_applied",
        incident_id=incident.id,
    )


@router.post("/push/register", response_model=MobilePushRegistrationResponse)
async def register_mobile_push_token(
    body: MobilePushRegistrationRequest,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobilePushRegistrationResponse:
    now = datetime.now(tz=UTC)
    device_session = await _current_device_session(session, claims)
    expected_device_hash = hash_mobile_lookup(body.installation_id, purpose="device-installation")
    if not hmac.compare_digest(expected_device_hash, device_session.device_identifier_hash):
        raise AuthorizationError("Push registration is not available")
    if (body.provider == "fcm" and device_session.platform != "android") or (
        body.provider == "apns" and device_session.platform != "ios"
    ):
        raise AuthorizationError("Push registration is not available")

    token_hash = hash_mobile_lookup(body.push_token, purpose="push-token")
    registration = (
        await session.execute(
            select(MobilePushRegistrationModel)
            .where(
                MobilePushRegistrationModel.provider == body.provider,
                MobilePushRegistrationModel.token_lookup_hash == token_hash,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if registration is not None and registration.session_id != claims.session_id:
        old_session = (
            await session.execute(
                select(MobileDeviceSessionModel).where(
                    MobileDeviceSessionModel.id == registration.session_id
                )
            )
        ).scalar_one_or_none()
        if old_session is None or not hmac.compare_digest(
            old_session.device_identifier_hash, device_session.device_identifier_hash
        ):
            raise AuthorizationError("Push registration is not available")

    ciphertext = _push_fernet().encrypt(body.push_token.encode("utf-8"))
    if registration is None:
        registration = MobilePushRegistrationModel(
            id=uuid.uuid4(),
            agency_id=claims.agency_id,
            session_id=claims.session_id,
            provider=body.provider,
            platform=device_session.platform,
            environment="production" if get_settings().is_production else "development",
            app_bundle_id=_APP_BUNDLE_ID,
            token_ciphertext=ciphertext,
            token_lookup_hash=token_hash,
            token_key_version=1,
            status="active",
            notifications_authorized=True,
            last_registered_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(registration)
    else:
        registration.agency_id = claims.agency_id
        registration.session_id = claims.session_id
        registration.platform = device_session.platform
        registration.environment = "production" if get_settings().is_production else "development"
        registration.app_bundle_id = _APP_BUNDLE_ID
        registration.token_ciphertext = ciphertext
        registration.token_key_version = 1
        registration.status = "active"
        registration.notifications_authorized = True
        registration.last_registered_at = now
        registration.last_failure_at = None
        registration.last_failure_code = None
        registration.revoked_at = None
        registration.updated_at = now

    previous_rows = list(
        (
            await session.execute(
                select(MobilePushRegistrationModel).where(
                    MobilePushRegistrationModel.session_id == claims.session_id,
                    MobilePushRegistrationModel.agency_id == claims.agency_id,
                    MobilePushRegistrationModel.provider == body.provider,
                    MobilePushRegistrationModel.id != registration.id,
                    MobilePushRegistrationModel.status == "active",
                )
            )
        ).scalars()
    )
    for previous in previous_rows:
        previous.status = "revoked"
        previous.revoked_at = now
        previous.updated_at = now
    await session.flush()
    return MobilePushRegistrationResponse(registration_id=registration.id)


@router.post("/push/unregister", response_model=MobilePushUnregisterResponse)
async def unregister_mobile_push_token(
    body: MobilePushUnregisterRequest,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobilePushUnregisterResponse:
    device_session = await _current_device_session(session, claims)
    expected_device_hash = hash_mobile_lookup(body.installation_id, purpose="device-installation")
    if not hmac.compare_digest(expected_device_hash, device_session.device_identifier_hash):
        raise AuthorizationError("Push registration is not available")
    statement = select(MobilePushRegistrationModel).where(
        MobilePushRegistrationModel.session_id == claims.session_id,
        MobilePushRegistrationModel.agency_id == claims.agency_id,
        MobilePushRegistrationModel.status != "revoked",
    )
    if body.provider is not None:
        statement = statement.where(MobilePushRegistrationModel.provider == body.provider)
    rows = list((await session.execute(statement.with_for_update())).scalars())
    now = datetime.now(tz=UTC)
    for registration in rows:
        registration.status = "revoked"
        registration.notifications_authorized = False
        registration.revoked_at = now
        registration.updated_at = now
    return MobilePushUnregisterResponse(revoked_count=len(rows))


@router.get("/notifications", response_model=MobileNotificationPageResponse)
async def list_mobile_notifications(
    trip_id: uuid.UUID | None = Query(default=None),
    cursor: uuid.UUID | None = Query(default=None),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=_MAX_NOTIFICATION_PAGE),
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileNotificationPageResponse:
    if trip_id is not None:
        await MobileAccessPolicy(session).require_trip_access(claims, trip_id)
    now = datetime.now(tz=UTC)
    recipient_filter = _notification_recipient_filter(claims)
    accessible_groups = _accessible_group_ids(claims, now)
    filters = [
        MobileNotificationModel.agency_id == claims.agency_id,
        recipient_filter,
        _published_announcement_notification_filter(claims.agency_id),
        MobileNotificationModel.notification_type.not_in(
            _PUSH_ONLY_NOTIFICATION_TYPES
        ),
        # A provider delivery failure must not remove the durable in-app update.
        MobileNotificationModel.status.in_(("queued", "sent", "failed")),
        MobileNotificationModel.available_at <= now,
        or_(
            MobileNotificationModel.expires_at.is_(None),
            MobileNotificationModel.expires_at > now,
        ),
        or_(
            MobileNotificationModel.group_id.is_(None),
            MobileNotificationModel.group_id.in_(accessible_groups),
        ),
    ]
    if trip_id is not None:
        filters.append(MobileNotificationModel.group_id == trip_id)
    if unread_only:
        filters.append(MobileNotificationModel.read_at.is_(None))
    unread_count = (
        await session.execute(
            select(func.count(MobileNotificationModel.id)).where(
                *filters,
                MobileNotificationModel.read_at.is_(None),
            )
        )
    ).scalar_one()
    if cursor is not None:
        filters.append(MobileNotificationModel.id < cursor)
    rows = list(
        (
            await session.execute(
                select(MobileNotificationModel)
                .where(*filters)
                .order_by(MobileNotificationModel.id.desc())
                .limit(limit + 1)
            )
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return MobileNotificationPageResponse(
        items=[_notification_response(item) for item in rows],
        next_cursor=str(rows[-1].id) if has_more and rows else None,
        unread_count=int(unread_count or 0),
    )


@router.post(
    "/notifications/{notification_id}/read",
    response_model=MobileNotificationReadResponse,
)
async def mark_mobile_notification_read(
    notification_id: uuid.UUID,
    claims: MobileAccessClaims = Depends(require_unrestricted_mobile_claims),
    session: AsyncSession = Depends(get_db_session),
) -> MobileNotificationReadResponse:
    notification = (
        await session.execute(
            select(MobileNotificationModel)
            .where(
                MobileNotificationModel.id == notification_id,
                MobileNotificationModel.agency_id == claims.agency_id,
                _notification_recipient_filter(claims),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if notification is None:
        raise EntityNotFoundError("Mobile notification", notification_id)
    if notification.group_id is not None:
        await MobileAccessPolicy(session).require_trip_access(claims, notification.group_id)
    if notification.read_at is None:
        notification.read_at = datetime.now(tz=UTC)
        notification.updated_at = notification.read_at
    return MobileNotificationReadResponse(id=notification.id, read_at=notification.read_at)


async def _require_coordinator_trip(
    session: AsyncSession,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
):
    if claims.principal_type != "coordinator":
        raise AuthorizationError("Coordinator group access is required")
    return await MobileAccessPolicy(session).require_trip_access(claims, group_id)


async def _require_client_manager_trip(
    session: AsyncSession,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
):
    if claims.principal_type != "client_manager":
        raise AuthorizationError("Client manager group access is required")
    return await MobileAccessPolicy(session).require_trip_access(claims, group_id)


async def _mobile_attendance_session(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    session_id: uuid.UUID,
    lock: bool,
) -> AttendanceSessionModel:
    statement = select(AttendanceSessionModel).where(
        AttendanceSessionModel.id == session_id,
        AttendanceSessionModel.canonical_session_id == session_id,
        AttendanceSessionModel.agency_id == claims.agency_id,
        AttendanceSessionModel.group_id == group_id,
    )
    if lock:
        statement = statement.with_for_update()
    value = (await session.execute(statement)).scalar_one_or_none()
    if value is None:
        raise EntityNotFoundError("Attendance activity", session_id)
    return value


async def _mobile_attendance_session_responses(
    session: AsyncSession,
    *,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    attendance_sessions: list[AttendanceSessionModel],
) -> list[MobileAttendanceSessionResponse]:
    if not attendance_sessions:
        return []
    assigned_count = int(
        (
            await session.execute(
                select(func.count(PassportSubmissionModel.id)).where(
                    PassportSubmissionModel.agency_id == claims.agency_id,
                    PassportSubmissionModel.group_id == group_id,
                    PassportSubmissionModel.status.in_(
                        OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
                    ),
                )
            )
        ).scalar_one()
        or 0
    )
    ids = [item.id for item in attendance_sessions]
    scan_counts = dict(
        (
            await session.execute(
                select(
                    AttendanceRecordModel.session_id,
                    func.count(func.distinct(AttendanceRecordModel.passenger_id)),
                )
                .where(
                    AttendanceRecordModel.agency_id == claims.agency_id,
                    AttendanceRecordModel.session_id.in_(ids),
                )
                .group_by(AttendanceRecordModel.session_id)
            )
        ).all()
    )
    return [
        MobileAttendanceSessionResponse(
            id=item.id,
            name=item.name,
            status=item.status,
            scanned_count=int(scan_counts.get(item.id, 0)),
            assigned_count=assigned_count,
            started_at=item.started_at,
            completed_at=item.completed_at,
        )
        for item in attendance_sessions
    ]


async def _latest_attendance_session(
    session: AsyncSession,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
) -> AttendanceSessionModel | None:
    return (
        await session.execute(
            select(AttendanceSessionModel)
            .where(
                AttendanceSessionModel.agency_id == claims.agency_id,
                AttendanceSessionModel.group_id == group_id,
                AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
                AttendanceSessionModel.status.in_(SCANNABLE_ATTENDANCE_STATUSES),
            )
            .order_by(
                case((AttendanceSessionModel.status == "active", 0), else_=1),
                AttendanceSessionModel.updated_at.desc(),
            )
            .limit(1)
        )
    ).scalar_one_or_none()


async def _attendance_session_for_action(
    session: AsyncSession,
    claims: MobileAccessClaims,
    group_id: uuid.UUID,
    *,
    requested_session_id: uuid.UUID | None,
) -> AttendanceSessionModel | None:
    statement = select(AttendanceSessionModel).where(
        AttendanceSessionModel.agency_id == claims.agency_id,
        AttendanceSessionModel.group_id == group_id,
        AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
        AttendanceSessionModel.status.in_(SCANNABLE_ATTENDANCE_STATUSES),
    )
    if requested_session_id is not None:
        return (
            await session.execute(
                statement.where(AttendanceSessionModel.id == requested_session_id).limit(1)
            )
        ).scalar_one_or_none()
    candidates = list(
        (
            await session.execute(
                statement.order_by(AttendanceSessionModel.updated_at.desc()).limit(2)
            )
        ).scalars()
    )
    return candidates[0] if len(candidates) == 1 else None


async def _current_device_session(
    session: AsyncSession,
    claims: MobileAccessClaims,
) -> MobileDeviceSessionModel:
    value = (
        await session.execute(
            select(MobileDeviceSessionModel).where(
                MobileDeviceSessionModel.id == claims.session_id,
                MobileDeviceSessionModel.agency_id == claims.agency_id,
                MobileDeviceSessionModel.status == "active",
                MobileDeviceSessionModel.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if value is None:
        raise AuthorizationError("Mobile device session is not available")
    return value


def _push_fernet() -> Fernet:
    """Compatibility shim for focused registration tests."""

    return mobile_push_fernet()


def _attendance_rejection_code(value: str | None) -> str:
    mapping = {
        "unknown_token": "QR_UNKNOWN",
        "revoked": "QR_REVOKED",
        "expired": "QR_EXPIRED",
        "inactive": "QR_INACTIVE",
        "wrong_group": "QR_WRONG_GROUP",
    }
    return mapping.get(value or "", "QR_INVALID")
