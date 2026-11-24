"""Create the fixed synthetic tenant/user/roster data in its existing transaction."""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.core.security.password import hash_password
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    NotificationModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.qr.approved_passenger_qr_issuer import qr_hash
from app.infrastructure.repositories.refresh_token_repository import (
    RefreshTokenRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from capacity_fixture_contract import LARGE_GROUP, SMALL_GROUP, TENANTS, identifier
from capacity_mcp_fixtures import seed_mcp
from upload_configuration_http_smoke import REQUIRED_FIELD_NAMES


async def seed(run_id: str) -> dict:
    observed = datetime.now(UTC)
    password_hash = hash_password("Synthetic-only-capacity-account-69371!")
    actors: list[dict[str, Any]] = []
    coordinators: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    async with AsyncSessionFactory() as db:
        for tenant in range(TENANTS):
            agency = identifier(run_id, f"agency-{tenant}")
            group_id = identifier(run_id, f"group-{tenant}")
            owner_id = identifier(run_id, f"staff-{tenant}-1")
            size = LARGE_GROUP if tenant == 0 else SMALL_GROUP
            db.add(
                AgencyModel(
                    id=agency,
                    name=f"Synthetic capacity tenant {tenant}",
                    email=f"{run_id}-{tenant}@example.test",
                )
            )
            await db.flush()
            for index in range(3):
                user_id = identifier(run_id, f"staff-{tenant}-{index}")
                role = ("agency_admin", "agency_staff", "agency_coordinator")[index]
                db.add(
                    UserModel(
                        id=user_id,
                        agency_id=agency,
                        email=f"{run_id}-{tenant}-{index}@example.test",
                        full_name="Synthetic capacity operator",
                        role=role,
                        is_active=True,
                        hashed_password=password_hash,
                    )
                )
                await db.flush()
                db.add(
                    UserSecurityStateModel(
                        user_id=user_id,
                        credential_state="active",
                        session_version=1,
                        password_changed_at=observed,
                        mfa_required=False,
                    )
                )
                await db.flush()
                repository = UserRepository(db)
                user = await repository.get_by_id(user_id)
                assert user is not None
                issued = await LoginUseCase(repository, RefreshTokenRepository(db)).issue_session(
                    user
                )
                actor: dict[str, Any] = {
                    "tenant": tenant,
                    "user_id": str(user_id),
                    "token": issued.access_token,
                    "group_id": str(group_id),
                    "group_size": size,
                    "role": role,
                }
                (actors if index < 2 else coordinators).append(actor)
            db.add(
                ClientGroupModel(
                    id=group_id,
                    agency_id=agency,
                    created_by_user_id=owner_id,
                    name=f"Synthetic capacity roster {tenant}",
                    token=f"capacity-{run_id}-{tenant}",
                    status="active",
                    destination="Synthetic destination",
                    travel_date=observed.date(),
                    return_date=observed.date() + timedelta(days=3),
                )
            )
            await db.flush()
            session_id = identifier(run_id, f"attendance-{tenant}")
            db.add(
                AttendanceSessionModel(
                    id=session_id,
                    canonical_session_id=session_id,
                    agency_id=agency,
                    group_id=group_id,
                    name="Synthetic capacity activity",
                    normalized_name=f"synthetic capacity activity {run_id}",
                    status="active",
                    created_by_user_id=owner_id,
                    started_at=observed - timedelta(minutes=1),
                    scheduled_starts_at=observed - timedelta(hours=1),
                    scheduled_ends_at=observed + timedelta(hours=3),
                    schedule_timezone="Asia/Kolkata",
                    schedule_version=1,
                )
            )
            coordinator = coordinators[-1]
            db.add(
                CoordinatorGroupAssignmentModel(
                    id=uuid.uuid4(),
                    agency_id=agency,
                    group_id=group_id,
                    coordinator_user_id=uuid.UUID(coordinator["user_id"]),
                    assigned_by_user_id=owner_id,
                    active=True,
                )
            )
            coordinator["session_id"] = str(session_id)
            coordinator["qr_payloads"] = []
            for offset in range(0, size, 250):
                for index in range(offset, min(size, offset + 250)):
                    passport = identifier(run_id, f"passenger-{tenant}-{index}")
                    # A skewed duplicate cluster plus unique records exercises
                    # the duplicate-aware prepared view rather than empty data.
                    passport_number = (
                        f"P{tenant:02d}{index:05d}" if index >= 50 else f"DUP{tenant:02d}"
                    )
                    db.add(
                        PassportSubmissionModel(
                            id=passport,
                            group_id=group_id,
                            agency_id=agency,
                            client_name=f"Synthetic Traveller {tenant:02d} {index:05d}",
                            image_s3_key=f"qualification/capacity/{run_id}/{passport}.jpg",
                            status="confirmed",
                            confirmed_fields={
                                "passport_number": passport_number,
                                "given_names": f"Synthetic {index}",
                                "surname": f"Traveller {tenant}",
                            },
                        )
                    )
                await db.flush()
            for index in range(min(size, 100)):
                raw = (
                    base64.urlsafe_b64encode(
                        hashlib.sha256(f"{run_id}-{tenant}-{index}".encode()).digest()
                    )
                    .decode()
                    .rstrip("=")
                )
                payload = f"pdatt:{raw}"
                db.add(
                    PassengerQRTokenModel(
                        id=uuid.uuid4(),
                        agency_id=agency,
                        passenger_id=identifier(run_id, f"passenger-{tenant}-{index}"),
                        created_by_user_id=owner_id,
                        token_hash=qr_hash(payload),
                        qr_payload=payload,
                        is_active=True,
                        expires_at=observed + timedelta(days=2),
                    )
                )
                coordinator["qr_payloads"].append(payload)
            for actor in actors[-2:]:
                for index in range(100):
                    db.add(
                        NotificationModel(
                            id=uuid.uuid4(),
                            agency_id=agency,
                            user_id=uuid.UUID(actor["user_id"]),
                            type="capacity_fixture",
                            title="Synthetic notification",
                            message="Synthetic capacity fixture",
                            is_read=False,
                            dedupe_key=f"{run_id}-{index}",
                        )
                    )
            public_id = identifier(run_id, f"public-{tenant}")
            public_token = f"capacity-public-{run_id}-{tenant}"
            db.add(
                ClientGroupModel(
                    id=public_id,
                    agency_id=agency,
                    created_by_user_id=owner_id,
                    name="Synthetic capacity upload",
                    token=public_token,
                    status="active",
                    destination="Synthetic destination",
                    travel_date=observed.date(),
                    return_date=observed.date() + timedelta(days=3),
                    allow_files_from_device=True,
                    require_selfie=False,
                    upload_configuration={
                        "passport_upload_pages": ["cover", "back_cover"],
                        "passport_live_scan": False,
                        "required_fields": {name: False for name in REQUIRED_FIELD_NAMES},
                    },
                )
            )
            groups.append(
                {
                    "tenant": tenant,
                    "agency_id": str(agency),
                    "group_id": str(group_id),
                    "public_token": public_token,
                    "group_size": size,
                }
            )
        await db.commit()
    mcp_actors = await seed_mcp(run_id, groups, password_hash)
    return {
        "run_id": run_id,
        "created_at": observed.isoformat(),
        "actors": actors,
        "coordinators": coordinators,
        "groups": groups,
        "mcp_actors": mcp_actors,
        "dataset": {
            "tenants": TENANTS,
            "office_actors": len(actors),
            "agency_admins": TENANTS,
            "agency_staff": TENANTS,
            "coordinators": len(coordinators),
            "passports": LARGE_GROUP + (TENANTS - 1) * SMALL_GROUP,
            "largest_group": LARGE_GROUP,
            "small_group": SMALL_GROUP,
            "duplicate_cluster_per_group": 50,
            "direct_notification_rows": 2000,
            "external_notification_fanout": 0,
            "mcp_superadmin_actors": len(mcp_actors),
        },
    }


# Preserve the original function identity through capacity_fixtures.
for _export in (seed,):
    _export.__module__ = "capacity_fixtures"
del _export
