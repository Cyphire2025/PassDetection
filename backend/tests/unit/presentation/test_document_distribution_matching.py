from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import UserRole
from app.infrastructure.documents.document_matcher import DocumentMatcher
from app.presentation.api.v1.routes import document_distribution
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    SendDocumentBroadcastRequest,
)


def _recipient(
    *,
    agency_id: uuid.UUID,
    broadcast_id: uuid.UUID,
    phone: str,
    imported_fields: dict[str, object],
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        broadcast_group_id=broadcast_id,
        name="Asha Mehta",
        normalized_phone_number=phone,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        imported_fields=imported_fields,
        removed_at=None,
    )


def _passenger(
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    phone: str,
    name: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=group_id,
        client_name=name,
        client_phone=phone,
        family_head_phone=None,
        client_email=None,
        family_head_email=None,
        updated_at=datetime(2026, 8, 1, tzinfo=UTC),
        confirmed_fields={},
        extracted_fields={},
        staff_metadata={},
    )


@pytest.mark.asyncio
async def test_linked_excel_code_requires_unique_scoped_passenger_match(monkeypatch) -> None:
    agency_id = uuid.uuid4()
    foreign_agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    broadcast_id = uuid.uuid4()
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    passenger = _passenger(
        agency_id=agency_id,
        group_id=group_id,
        phone="9876543210",
        name="Asha Mehta",
    )
    scoped_recipient = _recipient(
        agency_id=agency_id,
        broadcast_id=broadcast_id,
        phone="9876543210",
        imported_fields={"agent_code": "8899"},
    )
    foreign_recipient = _recipient(
        agency_id=foreign_agency_id,
        broadcast_id=broadcast_id,
        phone="9876543210",
        imported_fields={"staff_code": "4455"},
    )
    linked = AsyncMock(
        return_value=(
            {broadcast_id: "Vietnam group"},
            [scoped_recipient, foreign_recipient],
        )
    )
    monkeypatch.setattr(document_distribution, "_linked_whatsapp_recipients", linked)

    identifiers = await document_distribution._linked_document_match_identifiers(
        AsyncMock(),
        group=group,
        passengers=[passenger],
        matcher=DocumentMatcher(),
    )

    assert {(item.passenger_id, item.value) for item in identifiers} == {(passenger.id, "8899")}
    assert all(item.agency_id == agency_id for item in identifiers)
    linked.assert_awaited_once_with(
        ANY,
        group=group,
        require_opt_in=False,
    )


@pytest.mark.asyncio
async def test_linked_excel_code_is_not_attached_to_ambiguous_passengers(
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    broadcast_id = uuid.uuid4()
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    recipient = _recipient(
        agency_id=agency_id,
        broadcast_id=broadcast_id,
        phone="9876543210",
        imported_fields={"agent_code": "8899"},
    )
    passengers = [
        _passenger(
            agency_id=agency_id,
            group_id=group_id,
            phone="9876543210",
            name=name,
        )
        for name in ("Asha Mehta", "Ravi Sharma")
    ]
    monkeypatch.setattr(
        document_distribution,
        "_linked_whatsapp_recipients",
        AsyncMock(return_value=({broadcast_id: "Vietnam group"}, [recipient])),
    )

    identifiers = await document_distribution._linked_document_match_identifiers(
        AsyncMock(),
        group=group,
        passengers=passengers,
        matcher=DocumentMatcher(),
    )

    assert identifiers == ()


@pytest.mark.asyncio
async def test_distribution_write_scope_reauthorizes_and_locks_actor_agency_group(
    monkeypatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    actor = SimpleNamespace(id=uuid.uuid4(), email="current@example.test")
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    current_user = SimpleNamespace(
        id=actor.id,
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN,
    )
    result = MagicMock()
    result.one_or_none.return_value = (actor, group)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    authorize = AsyncMock()
    monkeypatch.setattr(
        document_distribution,
        "AuthorizationPolicy",
        lambda _session: SimpleNamespace(require_export_data=authorize),
    )

    locked_actor, locked_group = await document_distribution._lock_active_document_scope(
        session,
        current_user=current_user,
        group_id=group_id,
        agency_id=agency_id,
    )

    assert locked_actor is actor
    assert locked_group is group
    authorize.assert_awaited_once_with(actor, group)
    statement = session.execute.await_args.args[0]
    rendered = str(statement)
    assert "JOIN agencies" in rendered
    assert "JOIN client_groups" in rendered
    assert "users.is_active IS true" in rendered
    assert "agencies.is_active IS true" in rendered
    assert "FOR UPDATE" in rendered
    assert statement.get_execution_options()["populate_existing"] is True


@pytest.mark.asyncio
async def test_distribution_roster_lock_is_tenant_scoped_and_stably_ordered() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session = MagicMock()
    session.execute = AsyncMock()

    await document_distribution._lock_document_passenger_roster(
        session,
        agency_id=agency_id,
        group_id=group_id,
    )

    statement = session.execute.await_args.args[0]
    rendered = str(statement)
    assert "passport_submissions.agency_id" in rendered
    assert "passport_submissions.group_id" in rendered
    assert "ORDER BY passport_submissions.id" in rendered
    assert "FOR UPDATE" in rendered


@pytest.mark.asyncio
async def test_linked_matching_source_locks_broadcasts_links_then_recipients() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    broadcast_id = uuid.uuid4()
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    broadcast = SimpleNamespace(
        id=broadcast_id,
        agency_id=agency_id,
        name="Vietnam group",
    )
    link = SimpleNamespace(
        id=uuid.uuid4(),
        client_group_id=group_id,
        broadcast_group_id=broadcast_id,
        agency_id=agency_id,
        created_by_user_id=uuid.uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    recipient = _recipient(
        agency_id=agency_id,
        broadcast_id=broadcast_id,
        phone="9876543210",
        imported_fields={"staff_code": "GC42"},
    )

    def _result(values: list[object]) -> MagicMock:
        result = MagicMock()
        result.scalars.return_value.all.return_value = values
        return result

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _result([broadcast_id]),
            _result([broadcast]),
            _result([link]),
            _result([recipient]),
        ]
    )

    source = await document_distribution._read_linked_document_match_source(
        session,
        group=group,
        lock=True,
    )

    assert source.linked_broadcasts == {broadcast_id: "Vietnam group"}
    statements = [str(call.args[0]) for call in session.execute.await_args_list]
    assert "ORDER BY client_group_whatsapp_broadcast_links.broadcast_group_id" in statements[0]
    assert "ORDER BY whatsapp_broadcast_groups.id" in statements[1]
    assert "FOR UPDATE" in statements[1]
    assert "ORDER BY client_group_whatsapp_broadcast_links.id" in statements[2]
    assert "FOR UPDATE" in statements[2]
    assert "ORDER BY whatsapp_broadcast_recipients.id" in statements[3]
    assert "FOR UPDATE" in statements[3]


def test_linked_matching_snapshot_tracks_recipient_codes_and_link_identity() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    broadcast_id = uuid.uuid4()
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    broadcast = SimpleNamespace(
        id=broadcast_id,
        agency_id=agency_id,
        name="Vietnam group",
    )
    link = SimpleNamespace(
        id=uuid.uuid4(),
        client_group_id=group_id,
        broadcast_group_id=broadcast_id,
        agency_id=agency_id,
        created_by_user_id=uuid.uuid4(),
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    recipient = _recipient(
        agency_id=agency_id,
        broadcast_id=broadcast_id,
        phone="9876543210",
        imported_fields={"staff_code": "GC42"},
    )
    original = document_distribution._linked_document_match_source_from_models(
        group=group,
        links=[link],
        broadcasts=[broadcast],
        recipients=[recipient],
    )

    recipient.imported_fields = {"staff_code": "GC99"}
    changed_code = document_distribution._linked_document_match_source_from_models(
        group=group,
        links=[link],
        broadcasts=[broadcast],
        recipients=[recipient],
    )
    replacement_link = SimpleNamespace(**{**vars(link), "id": uuid.uuid4()})
    changed_link = document_distribution._linked_document_match_source_from_models(
        group=group,
        links=[replacement_link],
        broadcasts=[broadcast],
        recipients=[recipient],
    )

    assert changed_code.snapshot != original.snapshot
    assert changed_link.snapshot != changed_code.snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("upload_mode", [True, False])
async def test_linked_identifier_or_link_churn_fails_precommit_closed(
    monkeypatch,
    upload_mode: bool,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    actor = SimpleNamespace(id=uuid.uuid4(), email="current@example.test")
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    passenger = _passenger(
        agency_id=agency_id,
        group_id=group_id,
        phone="9876543210",
        name="Asha Mehta",
    )
    events: list[str] = []

    async def _lock_scope(*_args, **_kwargs):
        events.append("group")
        return actor, group

    async def _read_source(*_args, **_kwargs):
        events.append("linked")
        return document_distribution._LinkedDocumentMatchSource(
            linked_broadcasts={},
            recipients=(),
            snapshot=(("recipient", "changed-staff-code-or-link"),),
        )

    async def _lock_roster(*_args, **_kwargs):
        events.append("passengers")

    async def _passengers(*_args, **_kwargs):
        return [passenger]

    monkeypatch.setattr(document_distribution, "_lock_active_document_scope", _lock_scope)
    monkeypatch.setattr(
        document_distribution,
        "_read_linked_document_match_source",
        _read_source,
    )
    monkeypatch.setattr(document_distribution, "_lock_document_passenger_roster", _lock_roster)
    monkeypatch.setattr(document_distribution, "_group_passengers", _passengers)

    with pytest.raises(HTTPException) as error:
        await document_distribution._lock_and_validate_document_match_scope(
            AsyncMock(),
            current_user=SimpleNamespace(id=actor.id),
            group_id=group_id,
            agency_id=agency_id,
            matcher=DocumentMatcher(),
            expected_roster_snapshot=document_distribution._document_match_roster_snapshot(
                [passenger]
            ),
            expected_source_snapshot=(("recipient", "original-staff-code-and-link"),),
            expected_supplemental_identifiers=() if upload_mode else None,
            required_passenger_id=None if upload_mode else passenger.id,
        )

    assert error.value.status_code == 409
    assert events == ["group", "linked", "passengers"]


@pytest.mark.asyncio
async def test_distribution_precommit_cleanup_never_masks_root_failure(monkeypatch) -> None:
    storage = MagicMock()
    storage.delete_files = AsyncMock(side_effect=RuntimeError("storage unavailable"))
    persist_cleanup = AsyncMock(return_value=uuid.uuid4())
    monkeypatch.setattr(
        document_distribution,
        "MinioStorageRepository",
        lambda: storage,
    )
    monkeypatch.setattr(
        document_distribution,
        "persist_storage_cleanup_job",
        persist_cleanup,
    )

    await document_distribution._cleanup_distribution_storage_keys(
        ["document-distribution/example.pdf"],
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        document_type="visa",
    )

    storage.delete_files.assert_awaited_once_with(["document-distribution/example.pdf"])
    persist_cleanup.assert_awaited_once()


@pytest.mark.asyncio
async def test_document_group_counts_use_constant_query_count() -> None:
    agency_id = uuid.uuid4()
    groups = [
        SimpleNamespace(
            id=uuid.uuid4(),
            name=name,
            status="active",
            destination="Bangkok",
            travel_date=None,
        )
        for name in ("Newest", "Older")
    ]
    groups_result = MagicMock()
    groups_result.scalars.return_value.all.return_value = groups
    assigned_result = MagicMock()
    assigned_result.all.return_value = [
        (groups[0].id, "visa", 2),
        (groups[1].id, "flight_ticket", 1),
    ]
    passenger_result = MagicMock()
    passenger_result.all.return_value = [
        (groups[0].id, 3),
        (groups[1].id, 4),
    ]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[groups_result, assigned_result, passenger_result])
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN,
    )

    response = await document_distribution.list_document_groups(
        current_user=current_user,
        session=session,
    )

    assert session.execute.await_count == 3
    assert [item.group_id for item in response] == [group.id for group in groups]
    assert [item.total_passengers for item in response] == [3, 4]
    assert response[0].visa_assigned_count == 2
    assert response[1].flight_ticket_assigned_count == 1
    passenger_statement = session.execute.await_args_list[2].args[0]
    rendered = str(passenger_statement)
    assert "GROUP BY passport_submissions.group_id" in rendered
    assert "passport_submissions.agency_id" in rendered


@pytest.mark.asyncio
async def test_refresh_batches_loads_remaining_documents_once() -> None:
    now = datetime.now(tz=UTC)
    batches = [
        SimpleNamespace(
            id=uuid.uuid4(),
            status="saved",
            saved_at=now,
            uploaded_count=99,
            matched_count=99,
            updated_at=now,
        )
        for _ in range(2)
    ]
    batches_result = MagicMock()
    batches_result.scalars.return_value.all.return_value = batches
    documents_result = MagicMock()
    documents_result.all.return_value = [
        (batches[0].id, "matched"),
        (batches[0].id, "needs_review"),
        (batches[1].id, "matched"),
    ]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[batches_result, documents_result])

    await document_distribution._refresh_distribution_batches(
        session,
        batch_ids={batch.id for batch in batches},
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        now=now,
    )

    assert session.execute.await_count == 2
    assert (batches[0].uploaded_count, batches[0].matched_count) == (2, 1)
    assert (batches[1].uploaded_count, batches[1].matched_count) == (1, 1)
    assert all(batch.status == "draft" for batch in batches)
    assert all(batch.saved_at is None for batch in batches)


@pytest.mark.asyncio
async def test_batch_lookup_applies_tenant_and_group_visibility_at_first_query() -> None:
    agency_id = uuid.uuid4()
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    batch = await document_distribution._get_visible_document_batch(
        session,
        batch_id=uuid.uuid4(),
        current_user=current_user,
    )

    assert batch is None
    statement = session.execute.await_args.args[0]
    rendered = str(statement)
    assert "JOIN client_groups" in rendered
    assert "document_distribution_batches.agency_id" in rendered
    assert "client_groups.agency_id" in rendered


@pytest.mark.asyncio
async def test_foreign_group_id_returns_scoped_404_on_first_query() -> None:
    agency_id = uuid.uuid4()
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    with pytest.raises(HTTPException) as exc_info:
        await document_distribution._get_authorized_group(
            uuid.uuid4(),
            current_user=current_user,
            session=session,
        )

    assert exc_info.value.status_code == 404
    assert session.execute.await_count == 1
    rendered = str(session.execute.await_args.args[0])
    assert "client_groups.id" in rendered
    assert "client_groups.agency_id" in rendered


@pytest.mark.asyncio
async def test_foreign_batch_save_returns_404_before_group_authorization(
    monkeypatch,
) -> None:
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        role=UserRole.AGENCY_ADMIN,
    )
    lookup = AsyncMock(return_value=None)
    authorize_group = AsyncMock()
    monkeypatch.setattr(document_distribution, "_get_visible_document_batch", lookup)
    monkeypatch.setattr(document_distribution, "_get_authorized_group", authorize_group)

    with pytest.raises(HTTPException) as exc_info:
        await document_distribution.save_batch(
            batch_id=uuid.uuid4(),
            current_user=current_user,
            session=MagicMock(),
        )

    assert exc_info.value.status_code == 404
    authorize_group.assert_not_awaited()


@pytest.mark.asyncio
async def test_foreign_batch_send_returns_404_before_preview_or_queue_work(
    monkeypatch,
) -> None:
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        role=UserRole.AGENCY_ADMIN,
    )
    lookup = AsyncMock(return_value=None)
    authorize_group = AsyncMock()
    build_preview = AsyncMock()
    monkeypatch.setattr(document_distribution, "_get_visible_document_batch", lookup)
    monkeypatch.setattr(document_distribution, "_get_authorized_group", authorize_group)
    monkeypatch.setattr(
        document_distribution,
        "_build_document_delivery_preview",
        build_preview,
    )

    with pytest.raises(HTTPException) as exc_info:
        await document_distribution.send_document_whatsapp_broadcast(
            batch_id=uuid.uuid4(),
            payload=SendDocumentBroadcastRequest(
                message_content_1="Your document",
                message_content_2="Safe travels",
            ),
            current_user=current_user,
            session=MagicMock(),
        )

    assert exc_info.value.status_code == 404
    authorize_group.assert_not_awaited()
    build_preview.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_deliveries_are_batch_locked_with_exact_tenant_document_ownership() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    first_delivery_id = uuid.uuid4()
    second_delivery_id = uuid.uuid4()
    first_document_id = uuid.uuid4()
    second_document_id = uuid.uuid4()
    correct = SimpleNamespace(
        id=first_delivery_id,
        distributed_document_id=first_document_id,
    )
    mismatched = SimpleNamespace(
        id=second_delivery_id,
        distributed_document_id=first_document_id,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [correct, mismatched]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    locked = await document_distribution._lock_retry_document_deliveries(
        session,
        agency_id=agency_id,
        group_id=group_id,
        delivery_document_ids={
            first_delivery_id: first_document_id,
            second_delivery_id: second_document_id,
        },
    )

    assert locked == {first_delivery_id: correct}
    assert session.execute.await_count == 1
    statement = session.execute.await_args.args[0]
    rendered = str(statement)
    assert "document_whatsapp_deliveries.agency_id" in rendered
    assert "document_whatsapp_deliveries.group_id" in rendered
    assert "document_whatsapp_deliveries.distributed_document_id" in rendered
    assert "FOR UPDATE" in rendered
