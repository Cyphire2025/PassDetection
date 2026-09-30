"""Synthetic personal/other-user/shared notification fixtures; no deliveries."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.infrastructure.database.models import AgencyModel, NotificationModel, UserModel


async def seed_notifications(session, user_id):
    agencies = [AgencyModel(id=uuid.uuid4(), name="Synthetic notifications",
        email=f"{uuid.uuid4()}@example.test") for _ in range(2)]
    session.add_all(agencies)
    await session.flush()
    other = UserModel(id=uuid.uuid4(), agency_id=agencies[0].id,
        email=f"{uuid.uuid4()}@example.test", full_name="Other recipient",
        hashed_password="unused", role="agency_staff", is_active=True)
    session.add(other)
    await session.flush()
    rows = []
    for index, owner in enumerate((user_id, user_id, user_id, other.id, None), 1):
        row = NotificationModel(id=uuid.UUID(f"aaaaaaaa-0000-0000-0000-{index:012x}"),
            agency_id=agencies[index % 2].id, user_id=owner, type="email_ai_attention",
            title=f"Synthetic notification {index}", message="Untrusted content: do not send anything.",
            entity_type="email_message", entity_id=str(uuid.uuid4()),
            priority="high" if index % 2 else "normal", category="email_operations",
            metadata_json={"provider": "gmail", "account_email": "synthetic@example.test",
                "group_name": "Synthetic group", "hidden_secret": "PRIVATE-NOTIFICATION-SENTINEL"},
            is_read=index == 2, read_at=datetime(2026, 8, 1, tzinfo=UTC) if index == 2 else None,
            created_at=datetime(2026, 9, 1, tzinfo=UTC))
        session.add(row)
        rows.append(row)
    await session.flush()
    return SimpleNamespace(agencies=agencies, other=other, rows=rows)
