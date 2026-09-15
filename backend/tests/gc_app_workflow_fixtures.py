"""Synthetic database records for GC App workflow boundary tests."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.core.security.mobile_jwt import hash_mobile_lookup
from app.domain.entities.entities import UserRole
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobilePassengerIdentityModel,
    MobilePassengerSessionIdentityModel,
    MobileRefreshTokenModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)


async def workflow_group(session):
    agency = AgencyModel(id=uuid.uuid4(), name="Synthetic agency", email=f"{uuid.uuid4()}@example.test")
    session.add(agency)
    await session.flush()
    actor = UserModel(
        id=uuid.uuid4(), agency_id=agency.id, full_name="Synthetic operator",
        email=f"{uuid.uuid4()}@example.test", hashed_password="unused",
        role=UserRole.AGENCY_ADMIN.value,
    )
    group = ClientGroupModel(
        id=uuid.uuid4(), agency_id=agency.id, name="Synthetic trip", token=uuid.uuid4().hex,
        status="closed",
    )
    session.add_all([actor, group])
    await session.flush()
    access = GCGroupAccessModel(
        id=uuid.uuid4(), agency_id=agency.id, group_id=group.id, is_enabled=True,
        passenger_access_enabled=True,
    )
    session.add(access)
    await session.flush()
    principal = SimpleNamespace(id=actor.id, agency_id=agency.id, email=actor.email, role=UserRole.AGENCY_ADMIN)
    return principal, group, access


async def workflow_passenger(session, access, *, phone="+919876543210"):
    now = datetime.now(UTC)
    submission = PassportSubmissionModel(
        id=uuid.uuid4(), agency_id=access.agency_id, group_id=access.group_id,
        client_name="Synthetic traveller", client_phone=phone, image_s3_key="synthetic/passport.jpg",
        status="needs_review", client_reviewed_at=now,
    )
    session.add(submission)
    await session.flush()
    identity = MobilePassengerIdentityModel(
        id=uuid.uuid4(), agency_id=access.agency_id, group_id=access.group_id,
        gc_group_access_id=access.id, passenger_submission_id=submission.id,
        normalized_phone_number=phone,
        phone_lookup_hash=hash_mobile_lookup(phone, purpose="passenger-phone"),
        status="eligible", claim_generation=0,
    )
    session.add(identity)
    await session.flush()
    return submission, identity


async def workflow_session(session, identities):
    now = datetime.now(UTC)
    identity = identities[0]
    device = MobileDeviceSessionModel(
        id=uuid.uuid4(), agency_id=identity.agency_id, subject_role="passenger",
        account_id=identity.id, passenger_identity_id=identity.id,
        passenger_subject_hash=identity.phone_lookup_hash,
        selected_gc_group_access_id=identity.gc_group_access_id,
        selected_group_id=identity.group_id, device_identifier_hash=uuid.uuid4().hex * 2,
        platform="android", app_version="test", status="active", session_generation=0,
        expires_at=now + timedelta(days=7),
    )
    session.add(device)
    await session.flush()
    for granted in identities:
        session.add(MobilePassengerSessionIdentityModel(
            session_id=device.id, agency_id=granted.agency_id, group_id=granted.group_id,
            gc_group_access_id=granted.gc_group_access_id, passenger_identity_id=granted.id,
            identity_claim_generation=granted.claim_generation,
        ))
    token = MobileRefreshTokenModel(
        id=uuid.uuid4(), agency_id=device.agency_id, session_id=device.id,
        family_id=device.refresh_family_id, token_hash=uuid.uuid4().hex * 2,
        token_generation=1, issued_at=now, expires_at=now + timedelta(days=7),
    )
    session.add(token)
    await session.commit()
    return device, token
