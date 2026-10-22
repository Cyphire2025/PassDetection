"""Synthetic browser-only fixtures for the isolated PostgreSQL qualification stack.

The contact helper substitutes external OTP delivery only; verification, proof
consumption, upload validation and final storage promotion use the real API.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from upload_configuration_http_smoke import REQUIRED_FIELD_NAMES

from app.core.config.settings import get_settings
from app.core.security.password import hash_password
from app.infrastructure.database.models import (
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    PassengerQRTokenModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.session import AsyncSessionFactory, engine
from app.infrastructure.qr.approved_passenger_qr_issuer import qr_hash

BROWSER_NAMES = ("chromium", "firefox", "webkit")
COORDINATOR_PASSWORD = "Browser-Workflow-Qualification-628!"


def require_isolated_database() -> None:
    if get_settings().database.db != "passdetection_ci_browser":
        raise RuntimeError("Only the disposable passdetection_ci_browser database is allowed")


async def seed_browser_workflows(
    db: AsyncSession, namespace: uuid.UUID, agency_id: uuid.UUID, group_id: uuid.UUID,
    owner_id: uuid.UUID, passenger_ids: tuple[uuid.UUID, ...], observed: datetime,
) -> dict[str, object]:
    require_isolated_database()
    details: dict[str, object] = {}
    for index, browser in enumerate(BROWSER_NAMES):
        user_id = uuid.uuid5(namespace, f"coordinator-{browser}")
        user = await db.get(UserModel, user_id)
        if user is None:
            user = UserModel(id=user_id)
            db.add(user)
        user.email = f"enterprise.coordinator.{browser}@example.com"
        user.hashed_password = hash_password(COORDINATOR_PASSWORD)
        user.full_name = f"Synthetic {browser} coordinator"
        user.role = "agency_coordinator"
        user.agency_id = agency_id
        user.is_active = True
        user.deleted_at = None
        await db.flush()
        security = await db.get(UserSecurityStateModel, user_id)
        if security is None:
            security = UserSecurityStateModel(user_id=user_id)
            db.add(security)
        security.credential_state = "active"
        security.mfa_required = False
        security.password_changed_at = observed
        assignment_id = uuid.uuid5(namespace, f"coordinator-assignment-{browser}")
        assignment = await db.get(CoordinatorGroupAssignmentModel, assignment_id)
        if assignment is None:
            assignment = CoordinatorGroupAssignmentModel(
                id=assignment_id, agency_id=agency_id, group_id=group_id,
                coordinator_user_id=user_id, assigned_by_user_id=owner_id,
            )
            db.add(assignment)
        assignment.active = True
        assignment.unassigned_at = None
        raw_token = base64.urlsafe_b64encode(hashlib.sha256(f"synthetic-qr-{browser}".encode()).digest()).decode().rstrip("=")
        payload = f"pdatt:{raw_token}"
        qr_id = uuid.uuid5(namespace, f"qr-{browser}")
        qr = await db.get(PassengerQRTokenModel, qr_id)
        if qr is None:
            qr = (await db.execute(select(PassengerQRTokenModel).where(
                PassengerQRTokenModel.passenger_id == passenger_ids[index],
                PassengerQRTokenModel.is_active.is_(True),
            ))).scalar_one_or_none()
        if qr is None:
            qr = PassengerQRTokenModel(id=qr_id, agency_id=agency_id, passenger_id=passenger_ids[index], created_by_user_id=owner_id)
            db.add(qr)
        qr.token_hash = qr_hash(payload)
        qr.qr_payload = payload
        qr.is_active = True
        qr.expires_at = observed + timedelta(days=2)
        # Each seed run gets a fresh synthetic activity. Earlier test attendance
        # remains intact, and an interrupted prior run cannot pre-count this one.
        session_id = uuid.uuid5(namespace, f"browser-session-{browser}-{observed.isoformat()}")
        db.add(AttendanceSessionModel(
            id=session_id, agency_id=agency_id, group_id=group_id,
            canonical_session_id=session_id, name=f"Browser {browser} activity",
            normalized_name=f"browser {browser} activity {observed.isoformat()}",
            status="active", created_by_user_id=owner_id,
            started_at=observed - timedelta(minutes=1),
            scheduled_starts_at=observed - timedelta(hours=1),
            scheduled_ends_at=observed + timedelta(hours=3),
            schedule_timezone="Asia/Kolkata", schedule_version=1,
        ))
        public_group_id = uuid.uuid5(namespace, f"public-upload-{browser}")
        public_group = await db.get(ClientGroupModel, public_group_id)
        if public_group is None:
            public_group = ClientGroupModel(id=public_group_id, agency_id=agency_id, created_by_user_id=owner_id)
            db.add(public_group)
        public_group.name = f"Synthetic {browser} upload"
        public_group.token = f"enterprise-browser-public-{browser}-qa"
        public_group.status = "active"
        public_group.deleted_at = None
        public_group.destination = "Synthetic destination"
        public_group.travel_date = observed.date() + timedelta(days=30)
        public_group.return_date = observed.date() + timedelta(days=33)
        public_group.allow_files_from_device = True
        public_group.require_selfie = False
        public_group.upload_configuration = {
            "passport_upload_pages": ["cover", "back_cover"], "passport_live_scan": False,
            "required_fields": {name: False for name in REQUIRED_FIELD_NAMES},
        }
        details[browser] = {"email": user.email, "password": COORDINATOR_PASSWORD, "qr_payload": payload, "public_token": public_group.token, "session_id": str(session_id)}
    await db.flush()
    return details


async def main() -> None:
    from fresh_browser_workflow import inspect_publication, request_contact

    from app.application.travellers.draft_store import FreshDraftStore
    from app.core.config.traveller_reuse import get_traveller_reuse_settings
    from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto

    try:
        require_isolated_database()
        body = json.loads(sys.stdin.read(4096))
        operations = {"request_contact": request_contact, "inspect_publication": inspect_publication}
        operation = operations[body["operation"]]
        async with AsyncSessionFactory() as db:
            store = FreshDraftStore(db, get_settings(), TravellerReuseCrypto(get_traveller_reuse_settings()))
            print(json.dumps(await operation(store, body)))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
