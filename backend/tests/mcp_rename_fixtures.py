"""Synthetic rename metadata; no uploaded documents or storage objects."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.infrastructure.database.models import (
    AgencyModel,
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
    UserModel,
)


async def seed_rename_data(session, actor):
    agencies = [AgencyModel(id=uuid.uuid4(), name="Synthetic rename agency",
        email=f"{uuid.uuid4()}@example.test", is_active=index == 1) for index in range(2)]
    session.add_all(agencies)
    await session.flush()
    actor.agency_id = agencies[0].id
    staff = UserModel(id=uuid.uuid4(), agency_id=agencies[0].id, email=f"{uuid.uuid4()}@example.test",
        full_name="Synthetic staff", hashed_password="unused", role="agency_staff", is_active=True)
    session.add(staff)
    await session.flush()
    batches = []
    for index in range(4):
        row = DocumentRenameBatchModel(id=uuid.uuid4(), agency_id=agencies[1 if index == 3 else 0].id,
            title=f"Potentially personal title {index}", status="processing" if index == 1 else "completed",
            total_count=99, visa_count=1, ticket_count=2, unknown_count=96,
            created_by_user_id=staff.id if index == 2 else actor.id,
            created_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(days=index))
        session.add(row)
        batches.append(row)
    await session.flush()
    items = []
    for index, (detected, status, storage) in enumerate([
        ("visa", "renamed", "private/DO-NOT-HYDRATE"), ("flight_ticket", "needs_review", "private/DO-NOT-HYDRATE"),
        ("visa", "rejected", "private/DO-NOT-HYDRATE"), ("unknown", "renamed", "private/DO-NOT-HYDRATE"),
        ("visa", "renamed", ""), ("flight_ticket_arrival", "renamed", "private/DO-NOT-HYDRATE"),
    ], 1):
        row = DocumentRenameItemModel(id=uuid.UUID(f"bbbbbbbb-0000-0000-0000-{index:012x}"),
            agency_id=agencies[0].id, batch_id=batches[0].id, original_filename=f"Original person {index}.pdf",
            renamed_filename=f"Person {index // 2}.pdf", detected_type=detected, status=status, storage_key=storage,
            extracted_name="PRIVATE-EXTRACTED-NAME", extracted_passport_number="PRIVATE-PASSPORT",
            extracted_reference="PRIVATE-REFERENCE", reason="Potentially personal reason",
            created_at=datetime(2026, 9, 2, tzinfo=UTC))
        items.append(row)
        session.add(row)
    await session.flush()
    return SimpleNamespace(agencies=agencies, staff=staff, batches=batches, items=items)
