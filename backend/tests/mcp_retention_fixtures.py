"""Retained legacy schedule records, never cleanup candidates for a real worker."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.infrastructure.database.models import AgencyModel, ClientGroupModel


async def seed_retention_schedules(session, actor, *, opaque_size=1024):
    now = datetime.now(UTC)
    agencies = [
        AgencyModel(
            id=uuid.uuid4(),
            name="PRIVATE_AGENCY",
            email=f"{uuid.uuid4()}@example.test",
            is_active=active,
        )
        for active in (False, True)
    ]
    session.add_all(agencies)
    await session.flush()
    groups = []
    for agency in agencies:
        for index, status in enumerate(("active", "closed", "archived", "deleted")):
            group = ClientGroupModel(
                id=uuid.uuid4(),
                agency_id=agency.id,
                name="PRIVATE_GROUP",
                token=uuid.uuid4().hex,
                status=status,
                notes="SECRET_NOTES" + "界" * opaque_size,
                deleted_at=now if status == "deleted" else None,
                passport_purge_at=None if index == 0 else now + timedelta(days=index - 2),
                passport_retention_days_applied=None
                if index in (0, 2)
                else (1 if index == 1 else 3650),
                passport_legal_hold=True,
                passport_legal_hold_reason="SECRET_RETIRED_HOLD",
                passport_legal_hold_set_at=now,
                passport_legal_hold_set_by_user_id=actor.id,
            )
            session.add(group)
            groups.append(group)
    await session.flush()
    return SimpleNamespace(agencies=agencies, groups=groups)
