"""Synthetic cross-agency, retained-parent and all-status overview cohorts."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.domain.entities.entities import PassportProcessingStatus
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
)

GLOBAL_COUNTS = dict(agencies=2, users=6, client_groups=8, passport_submissions=48,
    pending_review=12, client_submitted=24, failed=4)
AGENCY_COUNTS = dict(agencies=1, users=2, client_groups=4, passport_submissions=24,
    pending_review=6, client_submitted=12, failed=2)
NULL_AGENCY_COUNTS = dict(agencies=0, users=2, client_groups=0, passport_submissions=0,
    pending_review=0, client_submitted=0, failed=0)


async def seed_admin_overview(session, actor, *, opaque_size=1024):
    now = datetime.now(UTC)
    agencies = [AgencyModel(id=uuid.uuid4(), name="PRIVATE_AGENCY", email=f"{uuid.uuid4()}@example.test",
        is_active=bool(index)) for index in range(2)]
    session.add_all(agencies)
    await session.flush()
    users = [UserModel(id=uuid.uuid4(), agency_id=agency.id, email=f"{uuid.uuid4()}@example.test",
        full_name="PRIVATE_USER", hashed_password="SECRET_PASSWORD", role="agency_staff",
        is_active=not removed, deleted_at=now if removed else None)
        for agency in agencies for removed in (False, True)]
    users.append(UserModel(id=uuid.uuid4(), agency_id=None, email=f"{uuid.uuid4()}@example.test",
        full_name="PRIVATE_UNASSIGNED", hashed_password="SECRET_PASSWORD", role="agency_admin", is_active=False))
    session.add_all(users)
    groups, submissions = [], []
    for agency in agencies:
        for status in ("active", "closed", "archived", "deleted"):
            group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="PRIVATE_GROUP", token=uuid.uuid4().hex,
                status=status, import_only=status == "closed", return_date=(now-timedelta(days=100)).date(),
                deleted_at=now if status == "deleted" else None, notes="SECRET_NOTES" + "x" * opaque_size)
            session.add(group)
            await session.flush()
            groups.append(group)
            for state in PassportProcessingStatus:
                row = PassportSubmissionModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
                    client_name="PRIVATE_PERSON", client_email="PRIVATE_EMAIL@example.test", image_s3_key="SECRET_OBJECT",
                    status=state.value, extracted_fields={"SECRET_JSON": "x" * (opaque_size if not submissions else 32)},
                    error_message="SECRET_PROVIDER_ERROR")
                session.add(row)
                submissions.append(row)
    await session.flush()
    return SimpleNamespace(agencies=agencies, users=users, groups=groups, submissions=submissions,
        expected=GLOBAL_COUNTS, actor=actor.id)
