from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
    summarize_match_rows,
)
from app.presentation.api.v1.routes import client_groups
from app.presentation.api.v1.schemas.client_group_schemas import (
    ResolveUnidentifiedReplacementRequest,
)


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _resolution(
    *,
    submission_id: uuid.UUID,
    recipient_id: uuid.UUID | None,
    resolution_type: str = "replacement",
    status: str = "active",
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        client_group_id=uuid.uuid4(),
        submission_id=submission_id,
        broadcast_recipient_id=recipient_id,
        resolution_type=resolution_type,
        request_id=uuid.uuid4(),
        suppressed_recipient_ids=([str(recipient_id)] if recipient_id is not None else []),
        excluded_submission_ids=[],
        status=status,
        resolved_by_user_id=uuid.uuid4(),
        created_at=datetime.now(tz=UTC),
        restored_by_user_id=None,
        restored_at=None,
    )


def test_stored_uuid_list_deduplicates_and_ignores_corrupt_values() -> None:
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()

    assert client_groups._stored_uuid_list(  # noqa: SLF001
        [str(first_id), first_id, "bad-id", None, str(second_id)]
    ) == [first_id, second_id]
    assert client_groups._stored_uuid_list("not-a-list") == []  # noqa: SLF001


def test_replacement_and_rejection_rows_are_counted_without_double_counting_people() -> None:
    now = datetime.now(tz=UTC)
    replacement_submission_id = uuid.uuid4()
    rows = [
        SubmissionMatchRow(
            status="replacement",
            match_basis="manual_replacement",
            normalized_phone="+919000000001",
            recipient_ids=(uuid.uuid4(), uuid.uuid4()),
            submission_ids=(replacement_submission_id,),
            broadcast_ids=(uuid.uuid4(), uuid.uuid4()),
            broadcast_names=("North", "South"),
            recipient_names=("Old Traveller",),
            submission_names=("New Traveller",),
            updated_at=now,
            confidence="high",
            resolution_id=uuid.uuid4(),
        ),
        SubmissionMatchRow(
            status="not_submitted",
            match_basis=None,
            normalized_phone="+919000000002",
            recipient_ids=(uuid.uuid4(),),
            submission_ids=(),
            broadcast_ids=(uuid.uuid4(),),
            broadcast_names=("North",),
            recipient_names=("Still Going",),
            submission_names=(),
            updated_at=now,
        ),
        SubmissionMatchRow(
            status="rejected_upload",
            match_basis="manual_rejection",
            normalized_phone="+919000000003",
            recipient_ids=(),
            submission_ids=(uuid.uuid4(),),
            broadcast_ids=(),
            broadcast_names=(),
            recipient_names=(),
            submission_names=("Rejected Upload",),
            updated_at=now,
            confidence="high",
            resolution_id=uuid.uuid4(),
        ),
    ]

    counts = summarize_match_rows(rows)

    assert counts.total_recipients == 2
    assert counts.submitted_count == 1
    assert counts.not_submitted_count == 1
    assert counts.matched_submission_count == 1
    assert counts.replacement_count == 1
    assert counts.rejected_upload_count == 1


@pytest.mark.asyncio
async def test_replacement_request_id_replay_requires_identical_target() -> None:
    submission_id = uuid.uuid4()
    original_recipient_id = uuid.uuid4()
    existing = _resolution(
        submission_id=submission_id,
        recipient_id=original_recipient_id,
    )
    group = SimpleNamespace(id=existing.client_group_id, agency_id=existing.agency_id)
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result(existing))
    current_user = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com")
    body = ResolveUnidentifiedReplacementRequest(
        recipient_id=uuid.uuid4(),
        request_id=existing.request_id,
    )

    with (
        patch.object(
            client_groups,
            "_require_whatsapp_broadcast_access",
        ),
        patch.object(
            client_groups,
            "_require_managed_group",
            new=AsyncMock(return_value=group),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await client_groups.resolve_unidentified_as_replacement(
            link_id=group.id,
            submission_id=submission_id,
            body=body,
            current_user=current_user,
            session=session,
            _csrf=None,
        )

    assert exc_info.value.status_code == 409
    assert "request ID was already used" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_replacement_records_needs_review_candidates_as_excluded_uploads() -> None:
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        email="admin@example.com",
    )
    replacement_submission = SimpleNamespace(
        id=uuid.uuid4(),
    )
    selected_recipient = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        broadcast_group_id=uuid.uuid4(),
        name="Original traveller",
        phone_number="+91 90000 00002",
        normalized_phone_number="+919000000002",
        imported_fields={"staff_code": "GC42"},
        removed_at=None,
        suppressed_by_roster_resolution_id=None,
    )
    candidate_old_upload_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    match_rows = [
        SubmissionMatchRow(
            status="unmatched_submission",
            match_basis=None,
            normalized_phone="+919000000001",
            recipient_ids=(),
            submission_ids=(replacement_submission.id,),
            broadcast_ids=(),
            broadcast_names=(),
            recipient_names=(),
            submission_names=("Replacement",),
            updated_at=now,
        ),
        SubmissionMatchRow(
            status="needs_review",
            match_basis="entered_name",
            normalized_phone="+919000000002",
            recipient_ids=(selected_recipient.id,),
            submission_ids=(),
            broadcast_ids=(selected_recipient.broadcast_group_id,),
            broadcast_names=("Tour list",),
            recipient_names=("Original traveller",),
            submission_names=("Possible old upload",),
            updated_at=now,
            candidate_submission_ids=(candidate_old_upload_id,),
        ),
    ]
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result(None),
            _scalar_result(replacement_submission),
            _scalars_result([selected_recipient.broadcast_group_id]),
            _scalar_result(selected_recipient),
            _scalars_result([selected_recipient]),
            MagicMock(),
            MagicMock(),
            MagicMock(),
        ]
    )
    session.flush = AsyncMock()
    nested = AsyncMock()
    session.begin_nested.return_value = nested
    audit_repository = SimpleNamespace(record=AsyncMock())
    body = ResolveUnidentifiedReplacementRequest(
        recipient_id=selected_recipient.id,
        request_id=uuid.uuid4(),
    )

    with (
        patch.object(
            client_groups,
            "_require_whatsapp_broadcast_access",
        ),
        patch.object(
            client_groups,
            "_require_managed_group",
            new=AsyncMock(return_value=group),
        ),
        patch.object(
            client_groups,
            "_current_unresolved_match_context",
            new=AsyncMock(
                return_value=(
                    {selected_recipient.broadcast_group_id: "Tour list"},
                    [selected_recipient],
                    [replacement_submission],
                    match_rows,
                )
            ),
        ),
        patch.object(
            client_groups,
            "AuditLogRepository",
            return_value=audit_repository,
        ),
        patch.object(
            client_groups,
            "lock_whatsapp_broadcast_groups",
            new=AsyncMock(return_value=[selected_recipient.broadcast_group_id]),
        ),
        patch.object(
            client_groups,
            "suppress_active_replacement_recipients",
            new=AsyncMock(return_value=[]),
        ),
    ):
        response = await client_groups.resolve_unidentified_as_replacement(
            link_id=group.id,
            submission_id=replacement_submission.id,
            body=body,
            current_user=current_user,
            session=session,
            _csrf=None,
        )

    stored_resolution = session.add.call_args.args[0]
    assert stored_resolution.excluded_submission_ids == [str(candidate_old_upload_id)]
    assert stored_resolution.suppressed_recipient_ids == [str(selected_recipient.id)]
    assert (
        stored_resolution.replaced_recipient_normalized_phone
        == selected_recipient.normalized_phone_number
    )
    assert stored_resolution.original_recipient_name == selected_recipient.name
    assert stored_resolution.original_recipient_phone == selected_recipient.phone_number
    assert stored_resolution.original_recipient_imported_fields == {
        "staff_code": "GC42"
    }
    assert selected_recipient.suppressed_by_roster_resolution_id == response.id
    assert selected_recipient.removed_at is not None
    audit_repository.record.assert_awaited_once()


@pytest.mark.asyncio
async def test_replacement_revalidates_links_after_broadcast_locks() -> None:
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    broadcast_id = uuid.uuid4()
    submission = SimpleNamespace(id=uuid.uuid4())
    current_user = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com")
    unidentified_row = SubmissionMatchRow(
        status="unmatched_submission",
        match_basis=None,
        normalized_phone="+919000000001",
        recipient_ids=(),
        submission_ids=(submission.id,),
        broadcast_ids=(),
        broadcast_names=(),
        recipient_names=(),
        submission_names=("Replacement",),
        updated_at=datetime.now(tz=UTC),
    )
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result(None),
            _scalar_result(submission),
            _scalars_result([]),
        ]
    )
    lock_broadcasts = AsyncMock(return_value=[broadcast_id])

    with (
        patch.object(client_groups, "_require_whatsapp_broadcast_access"),
        patch.object(
            client_groups,
            "_require_managed_group",
            new=AsyncMock(return_value=group),
        ),
        patch.object(
            client_groups,
            "_current_unresolved_match_context",
            new=AsyncMock(
                return_value=(
                    {broadcast_id: "Tour list"},
                    [],
                    [submission],
                    [unidentified_row],
                )
            ),
        ),
        patch.object(
            client_groups,
            "lock_whatsapp_broadcast_groups",
            new=lock_broadcasts,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await client_groups.resolve_unidentified_as_replacement(
            link_id=group.id,
            submission_id=submission.id,
            body=ResolveUnidentifiedReplacementRequest(
                recipient_id=uuid.uuid4(),
                request_id=uuid.uuid4(),
            ),
            current_user=current_user,
            session=session,
            _csrf=None,
        )

    assert exc_info.value.status_code == 409
    assert "linked WhatsApp broadcasts changed" in str(exc_info.value.detail)
    lock_broadcasts.assert_awaited_once_with(
        session,
        agency_id=group.agency_id,
        broadcast_group_ids=[broadcast_id],
    )
    assert session.execute.await_count == 3
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_restoring_replacement_reactivates_only_its_suppressed_recipients() -> None:
    submission_id = uuid.uuid4()
    resolution = _resolution(
        submission_id=submission_id,
        recipient_id=uuid.uuid4(),
    )
    group = SimpleNamespace(
        id=resolution.client_group_id,
        agency_id=resolution.agency_id,
    )
    now = datetime.now(tz=UTC)
    recipient = SimpleNamespace(
        id=resolution.broadcast_recipient_id,
        agency_id=group.agency_id,
        broadcast_group_id=uuid.uuid4(),
        removed_at=now,
        suppressed_by_roster_resolution_id=resolution.id,
    )
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result(resolution),
            _scalars_result([recipient.broadcast_group_id]),
            _scalars_result([recipient]),
            MagicMock(),
        ]
    )
    session.flush = AsyncMock()
    audit_repository = SimpleNamespace(record=AsyncMock())
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        email="admin@example.com",
    )

    with (
        patch.object(
            client_groups,
            "_require_whatsapp_broadcast_access",
        ),
        patch.object(
            client_groups,
            "_require_managed_group",
            new=AsyncMock(return_value=group),
        ),
        patch.object(
            client_groups,
            "AuditLogRepository",
            return_value=audit_repository,
        ),
        patch.object(
            client_groups,
            "lock_whatsapp_broadcast_groups",
            new=AsyncMock(),
        ),
        patch.object(
            client_groups,
            "suppress_active_replacement_recipients",
            new=AsyncMock(return_value=[]),
        ),
    ):
        response = await client_groups.restore_roster_resolution(
            link_id=group.id,
            resolution_id=resolution.id,
            current_user=current_user,
            session=session,
            _csrf=None,
        )

    assert recipient.removed_at is None
    assert recipient.suppressed_by_roster_resolution_id is None
    assert resolution.status == "restored"
    assert resolution.restored_by_user_id == current_user.id
    assert resolution.restored_at is not None
    assert response.status == "restored"
    assert session.flush.await_count == 2
    audit_repository.record.assert_awaited_once()


@pytest.mark.asyncio
async def test_linked_broadcast_cannot_be_removed_while_replacement_is_active() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    broadcast_id = uuid.uuid4()
    existing_links_result = MagicMock()
    existing_links_result.scalars.return_value.all.return_value = [broadcast_id]
    active_replacement_result = MagicMock()
    active_replacement_result.scalar_one_or_none.return_value = uuid.uuid4()
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(),
            existing_links_result,
            active_replacement_result,
        ]
    )
    lock_broadcasts = AsyncMock(return_value=[broadcast_id])

    with (
        patch.object(
            client_groups,
            "_validate_broadcast_ids",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(
            client_groups,
            "lock_whatsapp_broadcast_groups",
            new=lock_broadcasts,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await client_groups._replace_whatsapp_links(  # noqa: SLF001
            session,
            group_id=group_id,
            agency_id=agency_id,
            created_by_user_id=uuid.uuid4(),
            broadcast_ids=[],
        )

    assert exc_info.value.status_code == 409
    assert "Restore the replacement first" in str(exc_info.value.detail)
    assert session.execute.await_count == 3
    lock_broadcasts.assert_awaited_once_with(
        session,
        agency_id=agency_id,
        broadcast_group_ids=[broadcast_id],
    )
    session.flush.assert_not_called()


@pytest.mark.asyncio
async def test_newly_linked_broadcast_is_reconciled_against_active_replacements() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    broadcast_id = uuid.uuid4()
    existing_links_result = MagicMock()
    existing_links_result.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            MagicMock(),
            existing_links_result,
            MagicMock(),
        ]
    )
    session.flush = AsyncMock()
    initial_summary = SimpleNamespace(id=broadcast_id, recipient_count=1)
    reconciled_summary = SimpleNamespace(id=broadcast_id, recipient_count=0)
    validate = AsyncMock(side_effect=[[initial_summary], [reconciled_summary]])
    suppress = AsyncMock(return_value=[])
    lock_broadcasts = AsyncMock(return_value=[broadcast_id])

    with (
        patch.object(client_groups, "_validate_broadcast_ids", new=validate),
        patch.object(
            client_groups,
            "suppress_active_replacement_recipients",
            new=suppress,
        ),
        patch.object(
            client_groups,
            "lock_whatsapp_broadcast_groups",
            new=lock_broadcasts,
        ),
    ):
        summaries, previous_ids, changed = await client_groups._replace_whatsapp_links(  # noqa: SLF001
            session,
            group_id=group_id,
            agency_id=agency_id,
            created_by_user_id=uuid.uuid4(),
            broadcast_ids=[broadcast_id],
        )

    assert changed is True
    assert previous_ids == []
    assert summaries == [reconciled_summary]
    suppress.assert_awaited_once()
    assert suppress.await_args.kwargs["broadcast_group_ids"] == [broadcast_id]
    lock_broadcasts.assert_awaited_once_with(
        session,
        agency_id=agency_id,
        broadcast_group_ids=[broadcast_id],
    )
    assert session.flush.await_count == 2


@pytest.mark.parametrize(
    ("resolution_type", "recipient_id", "changed_field"),
    [
        ("replacement", uuid.uuid4(), "submission"),
        ("replacement", uuid.uuid4(), "recipient"),
        ("rejected", None, "type"),
        ("rejected", uuid.uuid4(), "recipient"),
    ],
)
def test_integrity_retry_replay_rejects_every_mismatched_target(
    resolution_type: str,
    recipient_id: uuid.UUID | None,
    changed_field: str,
) -> None:
    client_group_id = uuid.uuid4()
    submission_id = uuid.uuid4()
    expected_recipient_id = recipient_id
    resolution = _resolution(
        submission_id=submission_id,
        recipient_id=recipient_id,
        resolution_type=resolution_type,
    )
    resolution.client_group_id = client_group_id
    expected_type = resolution_type

    if changed_field == "submission":
        resolution.submission_id = uuid.uuid4()
    elif changed_field == "recipient":
        resolution.broadcast_recipient_id = (
            uuid.uuid4() if expected_recipient_id is not None else uuid.uuid4()
        )
    elif changed_field == "type":
        resolution.resolution_type = "replacement"

    with pytest.raises(HTTPException) as exc_info:
        client_groups._require_matching_roster_resolution_replay(  # noqa: SLF001
            resolution,
            client_group_id=client_group_id,
            submission_id=submission_id,
            resolution_type=expected_type,
            broadcast_recipient_id=expected_recipient_id,
            conflict_detail="Request ID already used.",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Request ID already used."
