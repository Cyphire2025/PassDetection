from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.infrastructure.database.models import (
    PassportExportHistoryModel,
    PassportRosterResolutionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportHistoryRepository,
    validated_export_people_snapshot,
)


@pytest.mark.asyncio
async def test_record_keeps_cumulative_checkpoint_separate_from_payload() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    repository = PassportExportHistoryRepository(session)
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    user_id = uuid.uuid4()
    baseline_id = uuid.uuid4()
    request_id = uuid.uuid4()
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    third_id = uuid.uuid4()
    people = [
        {
            "submission_id": str(third_id),
            "client_name": "Original Name",
            "client_phone": "+919999999999",
            "client_email": "original@example.com",
            "passport_number": "P1234567",
        }
    ]

    model = await repository.record(
        group_id=group_id,
        agency_id=agency_id,
        export_kind="passport_images",
        export_mode="incremental",
        request_id=request_id,
        baseline_export_id=baseline_id,
        snapshot_submission_ids=[first_id, second_id, third_id],
        exported_submission_ids=[third_id],
        exported_people_snapshot=people,
        pending_recipient_count=0,
        artifact_metadata={"image_count": 2},
        created_by_user_id=user_id,
        actor_email="admin@example.com",
    )

    assert model.group_id == group_id
    assert model.agency_id == agency_id
    assert model.request_id == request_id
    assert model.baseline_export_id == baseline_id
    assert model.snapshot_submission_ids == [
        str(first_id),
        str(second_id),
        str(third_id),
    ]
    assert model.exported_submission_ids == [str(third_id)]
    people[0]["client_name"] = "Changed After Record"
    assert model.exported_people_snapshot == [
        {
            "submission_id": str(third_id),
            "client_name": "Original Name",
            "client_phone": "+919999999999",
            "client_email": "original@example.com",
            "passport_number": "P1234567",
        }
    ]
    assert model.total_available_count == 3
    assert model.exported_count == 1
    assert model.artifact_metadata == {"image_count": 2}
    assert model.status == "prepared"
    assert model.completed_at is None
    session.add.assert_called_once_with(model)
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("snapshot_ids", "exported_ids", "message"),
    [
        (
            lambda value, other: [value, value],
            lambda value, other: [value],
            "checkpoint submission IDs must be unique",
        ),
        (
            lambda value, other: [value, other],
            lambda value, other: [other, other],
            "payload submission IDs must be unique",
        ),
        (
            lambda value, other: [value],
            lambda value, other: [other],
            "must belong to the cumulative checkpoint",
        ),
    ],
)
async def test_record_rejects_non_deterministic_or_inconsistent_ids(
    snapshot_ids,
    exported_ids,
    message: str,
) -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    repository = PassportExportHistoryRepository(session)
    value = uuid.uuid4()
    other = uuid.uuid4()

    with pytest.raises(ValueError, match=message):
        await repository.record(
            group_id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            export_kind="passport_excel",
            export_mode="all",
            request_id=uuid.uuid4(),
            snapshot_submission_ids=snapshot_ids(value, other),
            exported_submission_ids=exported_ids(value, other),
            exported_people_snapshot=[],
            created_by_user_id=None,
            actor_email=None,
        )

    session.add.assert_not_called()
    session.flush.assert_not_awaited()


def test_export_and_roster_models_expose_database_integrity_guards() -> None:
    export_table = PassportExportHistoryModel.__table__
    resolution_table = PassportRosterResolutionModel.__table__
    recipient_table = WhatsAppBroadcastRecipientModel.__table__

    export_constraint_names = {constraint.name for constraint in export_table.constraints}
    assert "uq_passport_export_history_group_kind_request" in export_constraint_names
    assert "ck_passport_export_history_kind" in export_constraint_names
    assert "ck_passport_export_history_mode" in export_constraint_names
    assert "ck_passport_export_history_counts" in export_constraint_names
    assert "ck_passport_export_history_completion" in export_constraint_names
    export_indexes = {index.name: index for index in export_table.indexes}
    assert "ix_passport_export_history_group_kind_status_completed" in export_indexes

    resolution_constraint_names = {constraint.name for constraint in resolution_table.constraints}
    assert "uq_passport_roster_resolution_group_request" in resolution_constraint_names
    assert "ck_passport_roster_resolution_type" in resolution_constraint_names
    assert "ck_passport_roster_resolution_status" in resolution_constraint_names
    assert "ck_passport_roster_resolution_restored_at" in resolution_constraint_names
    assert "ck_passport_roster_resolution_recipient" in resolution_constraint_names

    indexes = {index.name: index for index in resolution_table.indexes}
    assert indexes["uq_passport_roster_resolutions_active_submission"].unique is True
    assert indexes["uq_passport_roster_resolutions_active_recipient"].unique is True
    assert (
        str(
            indexes["uq_passport_roster_resolutions_active_submission"].dialect_options[
                "postgresql"
            ]["where"]
        )
        == "status = 'active'"
    )

    suppression_column = recipient_table.c.suppressed_by_roster_resolution_id
    assert suppression_column.nullable is True
    suppression_foreign_key = next(iter(suppression_column.foreign_keys))
    assert suppression_foreign_key.target_fullname == "passport_roster_resolutions.id"
    assert suppression_foreign_key.use_alter is True
    assert suppression_foreign_key.name == "fk_whatsapp_recipient_roster_resolution"


def test_people_snapshot_requires_exact_order_count_and_string_fields() -> None:
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    canonical = validated_export_people_snapshot(
        [
            {
                "submission_id": str(first_id),
                "client_name": "First",
                "client_phone": None,
                "client_email": "first@example.com",
                "passport_number": "A1",
                "ignored_mutable_field": "not persisted",
            },
            {
                "submission_id": str(second_id),
                "client_name": "Second",
                "client_phone": "+910000000000",
                "client_email": None,
                "passport_number": None,
            },
        ],
        exported_submission_ids=[first_id, second_id],
    )

    assert [row["submission_id"] for row in canonical] == [
        str(first_id),
        str(second_id),
    ]
    assert "ignored_mutable_field" not in canonical[0]

    with pytest.raises(ValueError, match="aligned"):
        validated_export_people_snapshot(
            list(reversed(canonical)),
            exported_submission_ids=[first_id, second_id],
        )
    with pytest.raises(ValueError, match="payload count"):
        validated_export_people_snapshot(
            canonical[:1],
            exported_submission_ids=[first_id, second_id],
        )
    with pytest.raises(ValueError, match="client_phone"):
        validated_export_people_snapshot(
            [{**canonical[0], "client_phone": 123}],
            exported_submission_ids=[first_id],
        )


@pytest.mark.asyncio
async def test_history_listing_is_completed_only_and_database_paginated() -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = result
    repository = PassportExportHistoryRepository(session)

    rows = await repository.list_for_group(
        group_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        export_kind="passport_excel",
        created_by_user_id=uuid.uuid4(),
        offset=50,
        limit=25,
    )

    assert rows == []
    statement = session.execute.await_args.args[0]
    compiled = statement.compile()
    assert 50 in compiled.params.values()
    assert 25 in compiled.params.values()
    assert "passport_export_history.status" in str(statement)
    assert "passport_export_history.completed_at DESC" in str(statement)


@pytest.mark.asyncio
async def test_history_count_uses_the_same_completed_actor_scope() -> None:
    result = MagicMock()
    result.scalar_one.return_value = 143
    session = AsyncMock()
    session.execute.return_value = result
    repository = PassportExportHistoryRepository(session)
    user_id = uuid.uuid4()

    count = await repository.count_for_group(
        group_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        export_kind="passport_images",
        created_by_user_id=user_id,
    )

    assert count == 143
    statement = session.execute.await_args.args[0]
    statement_text = str(statement)
    assert "count(*)" in statement_text
    assert "passport_export_history.status" in statement_text
    assert "passport_export_history.created_by_user_id" in statement_text
