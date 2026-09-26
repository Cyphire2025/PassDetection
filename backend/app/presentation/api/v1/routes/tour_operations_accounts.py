"""Accounts for tour operations; preserve tenant, lock and transaction boundaries."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.security.password import hash_password, run_password_work
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import UserModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.tour_operations_response_support import (
    coordinator_responses as _coordinator_responses,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    CoordinatorResponse,
    CreateCoordinatorRequest,
    TourOperationsArchitectureResponse,
    TourOperationsPhaseResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.security.client_ip import trusted_client_ip

from .tour_operations_access import (
    COORDINATOR_ACCOUNT_ROLES,
    COORDINATOR_MANAGEMENT_ROLES,
    TOUR_OPERATION_ROLES,
    _agency_scope,
    _require_agency,
)

router = APIRouter()


@router.get(
    "/architecture",
    response_model=TourOperationsArchitectureResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Tour Operations module architecture status",
)
async def get_tour_operations_architecture(
    current_user: User = Depends(require_role(TOUR_OPERATION_ROLES)),
) -> TourOperationsArchitectureResponse:
    return TourOperationsArchitectureResponse(
        module="tour_operations",
        current_phase=8,
        principles=[
            "Coordinator-led operations, not vehicle management.",
            "QR codes contain opaque revocable tokens only.",
            "Attendance is stored separately from passport extraction data.",
            "Offline scan events must be idempotent before scanner rollout.",
            "Coordinator access is isolated from passport and admin workflows.",
        ],
        permissions={
            "agency_coordinator": [
                "assigned_groups",
                "assigned_passengers",
                "attendance_sessions",
                "qr_scanner",
                "attendance_history",
            ],
            "agency_admin": [
                "coordinator_management",
                "passenger_assignment",
                "session_monitoring",
                "attendance_history",
            ],
            "agency_manager": [
                "coordinator_management",
                "passenger_assignment",
                "session_monitoring",
                "attendance_history",
            ],
            "agency_staff": [
                "assigned_groups",
                "rooming_lists",
                "document_distribution",
                "document_rename_own_batches",
            ],
            "super_admin": [
                "all_agency_operations",
                "qr_revocation",
                "system_audit",
            ],
        },
        data_entities=[
            "coordinator_assignments",
            "passenger_qr_tokens",
            "attendance_sessions",
            "attendance_records",
        ],
        offline_strategy=[
            "Store pending scan events in IndexedDB on the coordinator PWA.",
            "Each scan carries a client_event_id for idempotent synchronization.",
            "Server prevents duplicate attendance through session/passenger uniqueness.",
            "UI must expose connectivity, pending sync count, and last sync time.",
        ],
        navigation=[
            "Dashboard sidebar entry for Tour Operations.",
            "Future mobile coordinator shell under a dedicated coordinator route.",
            "Future office views for sessions, progress, and missing passengers.",
        ],
        phases=[
            TourOperationsPhaseResponse(
                phase=1,
                name="Architecture and Planning",
                status="completed",
                scope=[
                    "permissions",
                    "QR security model",
                    "attendance entities",
                    "offline synchronization strategy",
                    "dashboard navigation",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=2,
                name="Scanner Proof of Concept",
                status="completed",
                scope=[
                    "camera permissions",
                    "continuous QR scanning",
                    "duplicate suppression",
                    "PWA install verification",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=3,
                name="Coordinator Module",
                status="completed",
                scope=[
                    "coordinator accounts",
                    "assigned groups",
                    "assigned passengers",
                    "even passenger distribution",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=4,
                name="Coordinator PWA Shell",
                status="completed",
                scope=[
                    "coordinator login shell",
                    "assigned groups",
                    "assigned passengers",
                    "mobile scanner entry point",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=5,
                name="Activity Attendance",
                status="completed",
                scope=[
                    "named attendance activities",
                    "group-specific scanner",
                    "idempotent QR scan counting",
                    "office attendance progress view",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=6,
                name="Offline Fast Scanner",
                status="completed",
                scope=[
                    "IndexedDB scan queue",
                    "offline snapshot storage",
                    "sub-second duplicate suppression",
                    "PWA route caching",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=7,
                name="QR Distribution",
                status="completed",
                scope=[
                    "office QR payload endpoint",
                    "printable passenger QR cards",
                    "manager-scoped group access",
                    "dashboard QR navigation",
                ],
            ),
            TourOperationsPhaseResponse(
                phase=8,
                name="Speed, Security, and WhatsApp Foundation",
                status="completed",
                scope=[
                    "strict QR payload validation",
                    "race-safe scan inserts",
                    "offline duplicate suppression",
                    "disconnected WhatsApp broadcast planner",
                    "dry-run WhatsApp provider contract",
                ],
            ),
        ],
    )


@router.get(
    "/coordinators",
    response_model=list[CoordinatorResponse],
    status_code=status.HTTP_200_OK,
    summary="List coordinator accounts",
)
async def list_coordinators(
    current_user: User = Depends(require_role(COORDINATOR_MANAGEMENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[CoordinatorResponse]:
    agency_id = _agency_scope(current_user)
    filters: list[ColumnElement[bool]] = [
        UserModel.role == UserRole.AGENCY_COORDINATOR.value,
        UserModel.deleted_at.is_(None),
    ]
    if agency_id is not None:
        filters.append(UserModel.agency_id == agency_id)
    result = await session.execute(
        select(UserModel).where(*filters).order_by(UserModel.created_at.desc())
    )
    coordinators = list(result.scalars().all())
    return await _coordinator_responses(session, coordinators)


@router.post(
    "/coordinators",
    response_model=CoordinatorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a coordinator account",
)
async def create_coordinator(
    body: CreateCoordinatorRequest,
    request: Request,
    current_user: User = Depends(require_role(COORDINATOR_ACCOUNT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> CoordinatorResponse:
    agency_id = _require_agency(current_user)
    email = str(body.email).lower().strip()
    existing = await session.execute(select(UserModel).where(UserModel.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists"
        )

    coordinator = UserModel(
        email=email,
        hashed_password=await run_password_work(hash_password, body.password),
        full_name=body.full_name.strip(),
        role=UserRole.AGENCY_COORDINATOR.value,
        agency_id=agency_id,
        is_active=True,
    )
    session.add(coordinator)
    await session.flush()
    await AuditLogRepository(session).record(
        action="account.created",
        entity_type="user_account",
        agency_id=coordinator.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(coordinator.id),
        ip_address=trusted_client_ip(request),
        metadata={"target_role": coordinator.role, "target_email": coordinator.email},
    )
    return (await _coordinator_responses(session, [coordinator]))[0]
