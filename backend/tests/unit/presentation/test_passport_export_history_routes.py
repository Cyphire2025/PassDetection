from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.domain.entities.entities import User, UserRole
from app.main import create_application
from app.presentation.api.v1.routes import passports


def _history(
    *,
    snapshot_ids: list[object],
    exported_ids: list[object] | None = None,
    total_available_count: int | None = None,
    exported_count: int | None = None,
    people: list[dict[str, str | None]] | None = None,
):
    payload_ids = exported_ids if exported_ids is not None else snapshot_ids
    return SimpleNamespace(
        id=uuid.uuid4(),
        snapshot_submission_ids=[str(value) for value in snapshot_ids],
        exported_submission_ids=[str(value) for value in payload_ids],
        total_available_count=(
            len(snapshot_ids) if total_available_count is None else total_available_count
        ),
        exported_count=(len(payload_ids) if exported_count is None else exported_count),
        exported_people_snapshot=(
            people
            if people is not None
            else [
                {
                    "submission_id": str(value),
                    "client_name": f"Passenger {index}",
                    "client_phone": None,
                    "client_email": None,
                    "passport_number": None,
                }
                for index, value in enumerate(payload_ids, start=1)
            ]
        ),
    )


def _user(*, agency_id: uuid.UUID | None = None) -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.test",
        hashed_password="hash",
        full_name="Admin",
        role=UserRole.AGENCY_ADMIN,
        agency_id=agency_id or uuid.uuid4(),
    )


def test_export_confirmation_header_is_visible_to_cross_origin_browsers() -> None:
    application = create_application()
    cors = next(
        middleware
        for middleware in application.user_middleware
        if middleware.cls is CORSMiddleware
    )

    assert {
        "Content-Disposition",
        "X-Passport-Export-History-ID",
    }.issubset(set(cors.kwargs["expose_headers"]))


def test_history_integrity_rejects_invalid_duplicate_and_mismatched_ids() -> None:
    valid_id = uuid.uuid4()

    assert passports._validated_export_history_ids(  # noqa: SLF001
        _history(snapshot_ids=[valid_id]),
        field_name="snapshot_submission_ids",
    ) == {valid_id}

    for corrupt in (
        _history(snapshot_ids=["not-a-uuid"]),
        _history(snapshot_ids=[valid_id, valid_id]),
        _history(snapshot_ids=[valid_id], total_available_count=2),
    ):
        with pytest.raises(ValueError):
            passports._validated_export_history_ids(  # noqa: SLF001
                corrupt,
                field_name="snapshot_submission_ids",
            )


def test_people_snapshot_is_read_from_history_in_original_order() -> None:
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    history = _history(
        snapshot_ids=[first_id, second_id],
        people=[
            {
                "submission_id": str(first_id),
                "client_name": "Frozen First",
                "client_phone": "+911",
                "client_email": "first@example.test",
                "passport_number": "P1",
            },
            {
                "submission_id": str(second_id),
                "client_name": "Frozen Second",
                "client_phone": "+912",
                "client_email": "second@example.test",
                "passport_number": "P2",
            },
        ],
    )

    people = passports._validated_export_history_people(history)  # noqa: SLF001

    assert [person["client_name"] for person in people] == [
        "Frozen First",
        "Frozen Second",
    ]


@pytest.mark.asyncio
async def test_incremental_payload_is_exact_current_set_difference_in_current_order() -> None:
    downloaded_id = uuid.uuid4()
    new_first_id = uuid.uuid4()
    new_second_id = uuid.uuid4()
    baseline = _history(snapshot_ids=[downloaded_id])
    submissions = [
        SimpleNamespace(id=new_first_id),
        SimpleNamespace(id=downloaded_id),
        SimpleNamespace(id=new_second_id),
    ]
    repository = SimpleNamespace(get_compatible_baseline=AsyncMock(return_value=baseline))

    with patch.object(
        passports,
        "PassportExportHistoryRepository",
        return_value=repository,
    ):
        payload, resolved_baseline = await passports._resolve_group_export_payload(  # noqa: SLF001
            AsyncMock(),
            group_id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            export_kind="passport_images",
            export_mode="incremental",
            baseline_export_id=baseline.id,
            submissions=submissions,
            created_by_user_id=None,
        )

    assert [submission.id for submission in payload] == [
        new_first_id,
        new_second_id,
    ]
    assert resolved_baseline is baseline
    repository.get_compatible_baseline.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "baseline_id", "expected_status"),
    [
        ("all", uuid.uuid4(), 400),
        ("incremental", None, 400),
    ],
)
async def test_export_mode_and_baseline_contract_is_strict(
    mode: str,
    baseline_id: uuid.UUID | None,
    expected_status: int,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await passports._resolve_group_export_payload(  # noqa: SLF001
            AsyncMock(),
            group_id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
            export_kind="passport_excel",
            export_mode=mode,  # type: ignore[arg-type]
            baseline_export_id=baseline_id,
            submissions=[SimpleNamespace(id=uuid.uuid4())],
            created_by_user_id=None,
        )

    assert exc_info.value.status_code == expected_status


@pytest.mark.asyncio
async def test_incremental_export_rejects_missing_corrupt_or_exhausted_baseline() -> None:
    submission_id = uuid.uuid4()
    cases = (
        (None, 404),
        (
            _history(
                snapshot_ids=[submission_id],
                total_available_count=2,
            ),
            409,
        ),
        (_history(snapshot_ids=[submission_id]), 409),
    )

    for baseline, expected_status in cases:
        repository = SimpleNamespace(get_compatible_baseline=AsyncMock(return_value=baseline))
        with (
            patch.object(
                passports,
                "PassportExportHistoryRepository",
                return_value=repository,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await passports._resolve_group_export_payload(  # noqa: SLF001
                AsyncMock(),
                group_id=uuid.uuid4(),
                agency_id=uuid.uuid4(),
                export_kind="passport_excel",
                export_mode="incremental",
                baseline_export_id=uuid.uuid4(),
                submissions=[SimpleNamespace(id=submission_id)],
                created_by_user_id=None,
            )
        assert exc_info.value.status_code == expected_status


@pytest.mark.asyncio
async def test_active_roster_decisions_remove_rejected_and_replaced_old_uploads() -> None:
    rejected_id = uuid.uuid4()
    replacement_id = uuid.uuid4()
    old_submission_id = uuid.uuid4()
    keep_id = uuid.uuid4()
    resolutions = [
        SimpleNamespace(
            id=uuid.uuid4(),
            resolution_type="rejected",
            submission_id=rejected_id,
            excluded_submission_ids=[],
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            resolution_type="replacement",
            submission_id=replacement_id,
            excluded_submission_ids=[str(old_submission_id)],
        ),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = resolutions
    session = AsyncMock()
    session.execute.return_value = result
    submissions = [
        SimpleNamespace(id=rejected_id),
        SimpleNamespace(id=replacement_id),
        SimpleNamespace(id=old_submission_id),
        SimpleNamespace(id=keep_id),
    ]

    filtered = await passports._without_rejected_roster_submissions(  # noqa: SLF001
        session,
        submissions,
        group_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
    )

    assert [submission.id for submission in filtered] == [
        replacement_id,
        keep_id,
    ]


@pytest.mark.asyncio
async def test_delete_guard_rejects_corrupt_active_resolution_references() -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        SimpleNamespace(
            id=uuid.uuid4(),
            submission_id=uuid.uuid4(),
            excluded_submission_ids=["invalid-id"],
        )
    ]
    session = AsyncMock()
    session.execute.return_value = result

    with pytest.raises(HTTPException) as exc_info:
        await passports._active_roster_resolution_references(  # noqa: SLF001
            session,
            group_id=uuid.uuid4(),
            agency_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 409
    assert "integrity check" in str(exc_info.value.detail)


def _prepared_history(
    *,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    status: str = "prepared",
    completed_at: datetime | None = None,
):
    submission_id = uuid.uuid4()
    return SimpleNamespace(
        id=uuid.uuid4(),
        group_id=group_id,
        export_kind="passport_images",
        export_mode="incremental",
        baseline_export_id=uuid.uuid4(),
        snapshot_submission_ids=[str(submission_id)],
        exported_submission_ids=[str(submission_id)],
        exported_people_snapshot=[
            {
                "submission_id": str(submission_id),
                "client_name": "Frozen Passenger",
                "client_phone": "+919000000000",
                "client_email": "frozen@example.test",
                "passport_number": "Z7654321",
            }
        ],
        total_available_count=1,
        exported_count=1,
        pending_recipient_count=0,
        artifact_metadata={
            "image_count": 2,
            "archive_bytes": 1234,
        },
        created_by_user_id=user_id,
        actor_email="admin@example.test",
        status=status,
        created_at=datetime(2026, 7, 24, 9, 0, tzinfo=UTC),
        completed_at=completed_at,
    )


@pytest.mark.asyncio
async def test_completion_is_actor_scoped_committed_and_audited_once() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    current_user = _user(agency_id=agency_id)
    history = _prepared_history(group_id=group_id, user_id=current_user.id)
    group_repository = SimpleNamespace(
        get_by_id=AsyncMock(return_value=SimpleNamespace(id=group_id))
    )
    authorization = SimpleNamespace(require_export_data=AsyncMock())
    history_repository = SimpleNamespace(
        get_for_completion=AsyncMock(return_value=history)
    )
    audit_repository = SimpleNamespace(record=AsyncMock())
    session = AsyncMock()

    with (
        patch.object(passports, "ClientGroupRepository", return_value=group_repository),
        patch.object(passports, "AuthorizationPolicy", return_value=authorization),
        patch.object(
            passports,
            "PassportExportHistoryRepository",
            return_value=history_repository,
        ),
        patch.object(passports, "AuditLogRepository", return_value=audit_repository),
    ):
        response = await passports.complete_passport_group_export_history(
            group_id=group_id,
            history_id=history.id,
            _csrf=None,
            current_user=current_user,
            session=session,
        )

    assert response.history_id == history.id
    assert response.status == "completed"
    assert history.status == "completed"
    assert history.completed_at == response.completed_at
    session.commit.assert_awaited_once()
    history_repository.get_for_completion.assert_awaited_once_with(
        history_id=history.id,
        group_id=group_id,
        agency_id=agency_id,
        created_by_user_id=current_user.id,
    )
    audit_repository.record.assert_awaited_once()
    audit_call = audit_repository.record.await_args.kwargs
    assert audit_call["action"] == "passport_group_images_exported"
    assert audit_call["metadata"]["submission_count"] == 1
    assert audit_call["metadata"]["image_count"] == 2


@pytest.mark.asyncio
async def test_completion_replay_is_idempotent_without_second_audit() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    current_user = _user(agency_id=agency_id)
    completed_at = datetime(2026, 7, 24, 10, 30, tzinfo=UTC)
    history = _prepared_history(
        group_id=group_id,
        user_id=current_user.id,
        status="completed",
        completed_at=completed_at,
    )
    audit_repository = SimpleNamespace(record=AsyncMock())
    session = AsyncMock()

    with (
        patch.object(
            passports,
            "ClientGroupRepository",
            return_value=SimpleNamespace(
                get_by_id=AsyncMock(return_value=SimpleNamespace(id=group_id))
            ),
        ),
        patch.object(
            passports,
            "AuthorizationPolicy",
            return_value=SimpleNamespace(require_export_data=AsyncMock()),
        ),
        patch.object(
            passports,
            "PassportExportHistoryRepository",
            return_value=SimpleNamespace(
                get_for_completion=AsyncMock(return_value=history)
            ),
        ),
        patch.object(passports, "AuditLogRepository", return_value=audit_repository),
    ):
        response = await passports.complete_passport_group_export_history(
            group_id=group_id,
            history_id=history.id,
            _csrf=None,
            current_user=current_user,
            session=session,
        )

    assert response.completed_at == completed_at
    audit_repository.record.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_hides_wrong_actor_or_scope_as_not_found() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    current_user = _user(agency_id=agency_id)
    history_repository = SimpleNamespace(
        get_for_completion=AsyncMock(return_value=None)
    )

    with (
        patch.object(
            passports,
            "ClientGroupRepository",
            return_value=SimpleNamespace(
                get_by_id=AsyncMock(return_value=SimpleNamespace(id=group_id))
            ),
        ),
        patch.object(
            passports,
            "AuthorizationPolicy",
            return_value=SimpleNamespace(require_export_data=AsyncMock()),
        ),
        patch.object(
            passports,
            "PassportExportHistoryRepository",
            return_value=history_repository,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await passports.complete_passport_group_export_history(
            group_id=group_id,
            history_id=uuid.uuid4(),
            _csrf=None,
            current_user=current_user,
            session=AsyncMock(),
        )

    assert exc_info.value.status_code == 404
    assert "Prepared download" in str(exc_info.value.detail)
    assert (
        history_repository.get_for_completion.await_args.kwargs[
            "created_by_user_id"
        ]
        == current_user.id
    )


@pytest.mark.asyncio
async def test_history_detail_keeps_frozen_people_after_source_record_is_deleted() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    current_user = _user(agency_id=agency_id)
    history = _prepared_history(
        group_id=group_id,
        user_id=current_user.id,
        status="completed",
        completed_at=datetime(2026, 7, 24, 11, 0, tzinfo=UTC),
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = result

    with (
        patch.object(
            passports,
            "ClientGroupRepository",
            return_value=SimpleNamespace(
                get_by_id=AsyncMock(return_value=SimpleNamespace(id=group_id))
            ),
        ),
        patch.object(
            passports,
            "AuthorizationPolicy",
            return_value=SimpleNamespace(require_export_data=AsyncMock()),
        ),
        patch.object(
            passports,
            "PassportExportHistoryRepository",
            return_value=SimpleNamespace(
                get_for_group=AsyncMock(return_value=history)
            ),
        ),
    ):
        response = await passports.get_passport_group_export_history_detail(
            group_id=group_id,
            history_id=history.id,
            page=1,
            page_size=50,
            current_user=current_user,
            session=session,
        )

    assert response.completed_at == history.completed_at
    assert len(response.items) == 1
    assert response.items[0].record_available is False
    assert response.items[0].client_name == "Frozen Passenger"
    assert response.items[0].passport_number == "Z7654321"
    executed_statement = session.execute.await_args.args[0]
    assert "passport_submissions.client_name" not in str(executed_statement)
