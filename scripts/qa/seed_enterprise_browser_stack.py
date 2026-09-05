"""Seed deterministic, isolated data for the real-stack Playwright lane.

This script is intentionally test-only. It never creates production defaults,
and it mutates only UUIDs derived from the ``passdetection-real-stack-qa``
namespace. The caller must point the normal backend settings at an isolated,
fully migrated PostgreSQL database.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config.settings import get_settings
from app.core.security.identity_security import encrypt_mfa_secret
from app.core.security.password import hash_password
from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceCloseoutCheckpointModel,
    AttendanceRecordModel,
    AttendanceSessionModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.session import (
    AsyncSessionFactory,
    engine,
)

NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "passdetection-real-stack-qa")
AGENCY_ID = uuid.uuid5(NAMESPACE, "agency")
GROUP_ID = uuid.uuid5(NAMESPACE, "group")
SESSION_ID = uuid.uuid5(NAMESPACE, "attendance-session")
PASSENGER_IDS = tuple(uuid.uuid5(NAMESPACE, f"passenger-{index}") for index in range(3))
MANAGER_PASSWORD = "Enterprise-Browser-QA-937!"
MANAGERS = {
    "admin": (
        uuid.uuid5(NAMESPACE, "admin"),
        "enterprise.browser.admin@example.test",
        "ONSWG4TFOQXXGZLE",
    ),
    "chromium": (
        uuid.uuid5(NAMESPACE, "manager-chromium"),
        "enterprise.browser.chromium@example.test",
        "JBSWY3DPEHPK3PXP",
    ),
    "webkit": (
        uuid.uuid5(NAMESPACE, "manager-webkit"),
        "enterprise.browser.webkit@example.test",
        "KRSXG5DSNFXGOIDB",
    ),
    "mobile": (
        uuid.uuid5(NAMESPACE, "manager-mobile"),
        "enterprise.browser.mobile@example.test",
        "MFRGGZDFMZTWQ2LK",
    ),
}
PRIMARY_MANAGER_ID = MANAGERS["chromium"][0]


async def seed() -> None:
    settings = get_settings()
    if not settings.is_development or not settings.database.db.startswith("passdetection_ci_"):
        raise RuntimeError("Browser fixtures require a development passdetection_ci_ database")
    observed = datetime.now(tz=UTC)
    async with AsyncSessionFactory() as session:
        await session.execute(
            delete(AttendanceCloseoutCheckpointModel).where(
                AttendanceCloseoutCheckpointModel.session_id == SESSION_ID
            )
        )
        await session.execute(
            delete(AttendanceRecordModel).where(AttendanceRecordModel.session_id == SESSION_ID)
        )

        agency = await session.get(AgencyModel, AGENCY_ID)
        if agency is None:
            agency = AgencyModel(
                id=AGENCY_ID,
                name="Local Review Workspace",
                email="enterprise.browser.agency@example.test",
            )
            session.add(agency)
        else:
            agency.name = "Local Review Workspace"
            agency.is_active = True

        for project_name, (manager_id, email, _mfa_secret) in MANAGERS.items():
            role = UserRole.SUPER_ADMIN.value if project_name == "admin" else UserRole.AGENCY_MANAGER.value
            manager = await session.get(UserModel, manager_id)
            if manager is None:
                manager = UserModel(
                    id=manager_id,
                    email=email,
                    hashed_password=hash_password(MANAGER_PASSWORD),
                    full_name="Local Administrator" if project_name == "admin" else f"{project_name.title()} Manager",
                    role=role,
                    agency_id=AGENCY_ID,
                    is_active=True,
                )
                session.add(manager)
            else:
                manager.email = email
                manager.hashed_password = hash_password(MANAGER_PASSWORD)
                manager.full_name = "Local Administrator" if project_name == "admin" else f"{project_name.title()} Manager"
                manager.role = role
                manager.agency_id = AGENCY_ID
                manager.is_active = True
                manager.deleted_at = None
        await session.flush()

        for manager_id, _email, mfa_secret in MANAGERS.values():
            security_state = await session.get(UserSecurityStateModel, manager_id)
            if security_state is None:
                security_state = UserSecurityStateModel(user_id=manager_id)
                session.add(security_state)
            security_state.credential_state = "active"
            security_state.session_version = max(
                security_state.session_version or 1,
                1,
            )
            security_state.password_changed_at = observed
            security_state.mfa_required = True
            security_state.mfa_secret_ciphertext = encrypt_mfa_secret(mfa_secret)
            security_state.mfa_enabled_at = observed - timedelta(days=1)
            security_state.mfa_last_counter = None
            security_state.updated_at = observed

        group = await session.get(ClientGroupModel, GROUP_ID)
        if group is None:
            group = ClientGroupModel(
                id=GROUP_ID,
                name="Travel Review Group",
                token="enterprise-browser-group-qa",
                agency_id=AGENCY_ID,
                status="active",
                created_by_user_id=PRIMARY_MANAGER_ID,
            )
            session.add(group)
        else:
            group.name = "Travel Review Group"
            group.status = "active"
            group.created_by_user_id = PRIMARY_MANAGER_ID
            group.deleted_at = None
        await session.flush()

        attendance_session = await session.get(AttendanceSessionModel, SESSION_ID)
        if attendance_session is None:
            attendance_session = AttendanceSessionModel(
                id=SESSION_ID,
                agency_id=AGENCY_ID,
                group_id=GROUP_ID,
                name="Airport reporting QA",
                normalized_name="airport reporting qa",
                canonical_session_id=SESSION_ID,
                status="active",
                created_by_user_id=PRIMARY_MANAGER_ID,
            )
            session.add(attendance_session)
        attendance_session.status = "active"
        attendance_session.started_at = observed - timedelta(minutes=30)
        attendance_session.completed_at = None
        attendance_session.cancelled_at = None
        attendance_session.scheduled_starts_at = observed - timedelta(hours=1)
        attendance_session.scheduled_ends_at = observed + timedelta(hours=3)
        attendance_session.schedule_timezone = "Asia/Kolkata"
        attendance_session.schedule_version = max(
            attendance_session.schedule_version or 1,
            1,
        )
        attendance_session.updated_at = observed

        for index, passenger_id in enumerate(PASSENGER_IDS, start=1):
            passenger = await session.get(PassportSubmissionModel, passenger_id)
            if passenger is None:
                passenger = PassportSubmissionModel(
                    id=passenger_id,
                    group_id=GROUP_ID,
                    agency_id=AGENCY_ID,
                    client_name=f"Browser Passenger {index}",
                    image_s3_key=f"enterprise-browser-qa/{passenger_id}.jpg",
                    status="confirmed",
                )
                session.add(passenger)
            else:
                passenger.group_id = GROUP_ID
                passenger.agency_id = AGENCY_ID
                passenger.client_name = f"Browser Passenger {index}"
                passenger.status = "confirmed"
                passenger.updated_at = observed
        from dashboard_visual_fixtures import seed_visual_records

        await seed_visual_records(
            session, namespace=NAMESPACE, agency_id=AGENCY_ID, group_id=GROUP_ID,
            owner_id=MANAGERS["admin"][0], passenger_ids=PASSENGER_IDS,
        )
        await session.commit()

    print(
        json.dumps(
            {
                "agency_id": str(AGENCY_ID),
                "manager_password": MANAGER_PASSWORD,
                "accounts": {
                    project_name: {
                        "email": email,
                        "mfa_secret": mfa_secret,
                    }
                    for project_name, (_manager_id, email, mfa_secret) in MANAGERS.items()
                },
                "group_id": str(GROUP_ID),
                "session_id": str(SESSION_ID),
                "passenger_count": len(PASSENGER_IDS),
                "passenger_ids": [str(value) for value in PASSENGER_IDS],
            },
            sort_keys=True,
        )
    )


async def main() -> None:
    try:
        await seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
