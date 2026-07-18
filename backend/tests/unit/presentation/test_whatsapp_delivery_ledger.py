from __future__ import annotations

import uuid
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, UploadFile
from openpyxl import Workbook
from sqlalchemy import UniqueConstraint, select

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.worker_runtime import (
    _load_sendable_recipient,
    _set_message_state,
    run_whatsapp_broadcast,
)
from app.presentation.api.v1.routes.whatsapp import (
    WhatsAppContactPreviewResponse,
    WhatsAppRecipientInput,
    _activate_recipient_models,
    _apply_provider_status_to_delivery_state,
    _excel_contact_preview_response,
    _normalized_recipient_inputs,
    _parse_excel_contacts,
    _provider_status_state_predicates,
    _recipient_delivery_counts,
    _recipient_response,
    get_broadcast_batch_status,
    preview_excel_contacts,
)
from app.presentation.api.v1.routes.whatsapp import (
    router as whatsapp_router,
)


def test_delivery_ledger_schema_is_generic_and_unique_per_recipient_type() -> None:
    constraints = WhatsAppRecipientMessageStateModel.__table__.constraints
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("recipient_id", "message_type") in unique_columns
    assert WhatsAppRecipientMessageStateModel.__table__.c.message_type.type.length == 64
    assert WhatsAppMessageLogModel.__table__.c.message_type.type.length == 64
    assert "removed_at" in WhatsAppBroadcastRecipientModel.__table__.c


def test_recipient_checklist_only_marks_provider_accepted_states_as_sent() -> None:
    recipient_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    recipient = SimpleNamespace(
        id=recipient_id,
        name="Aarav",
        phone_number="9876543210",
        normalized_phone_number="+919876543210",
    )
    states = [
        SimpleNamespace(
            recipient_id=recipient_id,
            message_type="welcome",
            status="delivered",
            submitted_at=now,
            status_updated_at=now,
        ),
        SimpleNamespace(
            recipient_id=recipient_id,
            message_type="passport_link",
            status="failed",
            submitted_at=None,
            status_updated_at=now,
        ),
    ]

    response = _recipient_response(recipient, states)

    assert response.sent_message_types == ["welcome"]
    assert [item.message_type for item in response.message_statuses] == [
        "passport_link",
        "welcome",
    ]
    assert {item.message_type: item.already_sent for item in response.message_statuses} == {
        "passport_link": False,
        "welcome": True,
    }


@pytest.mark.asyncio
async def test_eligibility_counts_failed_as_retryable_and_active_claim_as_skipped() -> None:
    recipient_ids = [uuid.uuid4() for _ in range(5)]
    recipients = [SimpleNamespace(id=recipient_id) for recipient_id in recipient_ids]
    result = MagicMock()
    result.all.return_value = [
        (recipient_ids[0], "submitted"),
        (recipient_ids[1], "processing"),
        (recipient_ids[2], "failed"),
        (recipient_ids[3], "delivery_unknown"),
    ]
    session = AsyncMock()
    session.execute.return_value = result

    eligible, already_sent, in_progress, uncertain = await _recipient_delivery_counts(
        session,
        recipients=recipients,
        message_type="welcome",
    )

    assert eligible == 2  # failed + never attempted
    assert already_sent == 1
    assert in_progress == 1
    assert uncertain == 1


def test_readding_removed_phone_reactivates_same_row_and_preserves_identity() -> None:
    recipient_id = uuid.uuid4()
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    existing = SimpleNamespace(
        id=recipient_id,
        name="Old Name",
        phone_number="9876543210",
        normalized_phone_number="+919876543210",
        removed_at=datetime.now(tz=UTC),
    )
    normalized = _normalized_recipient_inputs(
        [
            WhatsAppRecipientInput(
                name="Updated Name",
                phone_number="+91 98765 43210",
            )
        ]
    )
    session = MagicMock()

    _activate_recipient_models(
        session=session,
        group=group,
        existing_by_phone={existing.normalized_phone_number: existing},
        normalized_contacts=normalized,
        now=datetime.now(tz=UTC),
    )

    assert existing.id == recipient_id
    assert existing.removed_at is None
    assert existing.name == "Updated Name"
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_worker_acceptance_makes_inflight_provider_success_authoritative() -> None:
    batch_id = uuid.uuid4()
    log = SimpleNamespace(
        recipient_id=uuid.uuid4(),
        message_type="future_template_type",
    )
    session = AsyncMock()

    await _set_message_state(
        session,
        log=log,
        expected_batch_id=batch_id,
        state_status="submitted",
        submitted=True,
    )

    statement = session.execute.await_args.args[0]
    compiled = statement.compile()
    assert "recipient_id" in str(statement.whereclause)
    assert "message_type" in str(statement.whereclause)
    assert "status" in str(statement.whereclause)
    assert batch_id in compiled.params.values()
    assert "submitted" in compiled.params.values()
    assert any(isinstance(value, datetime) for value in compiled.params.values())


@pytest.mark.asyncio
async def test_worker_failure_releases_ledger_claim_for_safe_retry() -> None:
    batch_id = uuid.uuid4()
    log = SimpleNamespace(
        recipient_id=uuid.uuid4(),
        message_type="welcome",
    )
    session = AsyncMock()

    await _set_message_state(
        session,
        log=log,
        expected_batch_id=batch_id,
        state_status="failed",
        release_claim=True,
    )

    statement = session.execute.await_args.args[0]
    compiled = statement.compile()
    assert "failed" in compiled.params.values()
    assert None in compiled.params.values()


@pytest.mark.asyncio
async def test_worker_success_exits_retry_loop_and_remains_submitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch_id = uuid.uuid4()
    group_id = uuid.uuid4()
    recipient_id = uuid.uuid4()
    log = SimpleNamespace(
        id=uuid.uuid4(),
        batch_id=batch_id,
        broadcast_group_id=group_id,
        recipient_id=recipient_id,
        message_type="welcome",
        template_name="welcome_template",
        status="queued",
        status_updated_at=datetime.now(tz=UTC),
        provider_message_id=None,
        error_message=None,
        created_at=datetime.now(tz=UTC),
    )
    group = SimpleNamespace(
        id=group_id,
        name="Vietnam 2026",
        organizing_company_name="Bluechip",
    )
    recipient = SimpleNamespace(
        id=recipient_id,
        name="Aarav",
        normalized_phone_number="+919876543210",
    )

    logs_result = MagicMock()
    logs_result.scalars.return_value.all.return_value = [log]
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    support_result = MagicMock()
    support_result.scalars.return_value.all.return_value = []
    log_claim_result = MagicMock()
    log_claim_result.scalar_one_or_none.return_value = log.id
    state_claim_result = MagicMock()
    state_claim_result.scalar_one_or_none.return_value = uuid.uuid4()

    session = AsyncMock()
    session.execute.side_effect = [
        logs_result,
        group_result,
        support_result,
        log_claim_result,
        state_claim_result,
    ]

    class _AsyncContext:
        def __init__(self, value: object) -> None:
            self.value = value

        async def __aenter__(self) -> object:
            return self.value

        async def __aexit__(self, *args: object) -> None:
            return None

    client = SimpleNamespace()
    send_template = AsyncMock(return_value="wamid.success")
    load_recipient = AsyncMock(return_value=(recipient, None))
    set_state = AsyncMock()
    monkeypatch.setattr(
        "app.infrastructure.whatsapp.worker_runtime.AsyncSessionFactory",
        lambda: _AsyncContext(session),
    )
    monkeypatch.setattr(
        "app.infrastructure.whatsapp.worker_runtime.httpx.AsyncClient",
        lambda **_kwargs: _AsyncContext(client),
    )
    monkeypatch.setattr(
        "app.infrastructure.whatsapp.worker_runtime.send_whatsapp_template",
        send_template,
    )
    monkeypatch.setattr(
        "app.infrastructure.whatsapp.worker_runtime._load_sendable_recipient",
        load_recipient,
    )
    monkeypatch.setattr(
        "app.infrastructure.whatsapp.worker_runtime._set_message_state",
        set_state,
    )

    await run_whatsapp_broadcast(
        batch_id=str(batch_id),
        message_type="welcome",
        message_content="Welcome aboard",
        passport_link=None,
    )

    assert send_template.await_count == 1
    assert load_recipient.await_count == 2
    assert log.status == "submitted"
    assert log.provider_message_id == "wamid.success"
    assert set_state.await_args.kwargs["state_status"] == "submitted"
    assert set_state.await_args.kwargs["submitted"] is True


@pytest.mark.asyncio
async def test_worker_guard_rejects_removed_recipient_before_provider_call() -> None:
    recipient = SimpleNamespace(
        id=uuid.uuid4(),
        removed_at=datetime.now(tz=UTC),
    )
    recipient_result = MagicMock()
    recipient_result.scalar_one_or_none.return_value = recipient
    session = AsyncMock()
    session.execute.return_value = recipient_result

    sendable, reason = await _load_sendable_recipient(
        session,
        log=SimpleNamespace(
            recipient_id=recipient.id,
            broadcast_group_id=uuid.uuid4(),
            message_type="welcome",
        ),
        expected_batch_id=uuid.uuid4(),
    )

    assert sendable is None
    assert reason == "WhatsApp recipient was removed"
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_worker_guard_requires_current_processing_batch() -> None:
    batch_id = uuid.uuid4()
    recipient = SimpleNamespace(id=uuid.uuid4(), removed_at=None)
    recipient_result = MagicMock()
    recipient_result.scalar_one_or_none.return_value = recipient
    state_result = MagicMock()
    state_result.scalar_one_or_none.return_value = SimpleNamespace(
        batch_id=batch_id,
        status="processing",
    )
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = SimpleNamespace(id=uuid.uuid4())
    session = AsyncMock()
    session.execute.side_effect = [group_result, recipient_result, state_result]

    sendable, reason = await _load_sendable_recipient(
        session,
        log=SimpleNamespace(
            recipient_id=recipient.id,
            broadcast_group_id=group_result.scalar_one_or_none.return_value.id,
            message_type="welcome",
        ),
        expected_batch_id=batch_id,
    )

    assert sendable is recipient
    assert reason is None


def test_late_failed_receipt_does_not_regress_accepted_checklist() -> None:
    original_time = datetime(2026, 7, 18, tzinfo=UTC)
    state = SimpleNamespace(
        status="delivered",
        batch_id=uuid.uuid4(),
        submitted_at=original_time,
        status_updated_at=original_time,
        provider_status_at=original_time,
        updated_at=original_time,
    )

    _apply_provider_status_to_delivery_state(
        state,
        provider_status="failed",
        provider_status_at=datetime(2026, 7, 19, tzinfo=UTC),
        now=datetime(2026, 7, 19, tzinfo=UTC),
    )

    assert state.status == "delivered"
    assert state.batch_id is not None
    assert state.submitted_at == original_time


def test_out_of_order_accepted_receipt_never_moves_status_backwards() -> None:
    original_time = datetime(2026, 7, 18, tzinfo=UTC)
    state = SimpleNamespace(
        status="read",
        batch_id=uuid.uuid4(),
        submitted_at=original_time,
        status_updated_at=original_time,
        provider_status_at=original_time,
        updated_at=original_time,
    )

    _apply_provider_status_to_delivery_state(
        state,
        provider_status="sent",
        provider_status_at=datetime(2026, 7, 19, tzinfo=UTC),
        now=datetime(2026, 7, 19, tzinfo=UTC),
    )

    assert state.status == "read"


def test_failed_receipt_before_acceptance_releases_retry_claim() -> None:
    batch_id = uuid.uuid4()
    state = SimpleNamespace(
        status="processing",
        batch_id=batch_id,
        submitted_at=None,
        status_updated_at=datetime(2026, 7, 18, tzinfo=UTC),
        provider_status_at=None,
        updated_at=datetime(2026, 7, 18, tzinfo=UTC),
    )

    _apply_provider_status_to_delivery_state(
        state,
        provider_status="failed",
        provider_status_at=datetime(2026, 7, 19, tzinfo=UTC),
        now=datetime(2026, 7, 19, tzinfo=UTC),
    )

    assert state.status == "failed"
    assert state.batch_id == batch_id


def test_current_failed_receipt_releases_submitted_but_not_delivered() -> None:
    submitted_at = datetime(2026, 7, 18, tzinfo=UTC)
    provider_event_at = datetime(2026, 7, 19, tzinfo=UTC)
    batch_id = uuid.uuid4()
    state = SimpleNamespace(
        status="submitted",
        batch_id=batch_id,
        submitted_at=submitted_at,
        status_updated_at=submitted_at,
        provider_status_at=None,
        updated_at=submitted_at,
    )

    _apply_provider_status_to_delivery_state(
        state,
        provider_status="failed",
        provider_status_at=provider_event_at,
        now=provider_event_at,
    )

    assert state.status == "failed"
    assert state.batch_id == batch_id
    assert state.provider_status_at == provider_event_at


def test_older_provider_event_is_ignored() -> None:
    latest_event_at = datetime(2026, 7, 19, tzinfo=UTC)
    state = SimpleNamespace(
        status="delivered",
        batch_id=uuid.uuid4(),
        submitted_at=datetime(2026, 7, 18, tzinfo=UTC),
        status_updated_at=latest_event_at,
        provider_status_at=latest_event_at,
        updated_at=latest_event_at,
    )

    _apply_provider_status_to_delivery_state(
        state,
        provider_status="read",
        provider_status_at=datetime(2026, 7, 18, tzinfo=UTC),
        now=datetime(2026, 7, 20, tzinfo=UTC),
    )

    assert state.status == "delivered"
    assert state.provider_status_at == latest_event_at


def test_late_accepted_receipt_promotes_ledger_across_retry_batches() -> None:
    log = SimpleNamespace(
        recipient_id=uuid.uuid4(),
        message_type="welcome",
        batch_id=uuid.uuid4(),
    )

    statement = select(WhatsAppRecipientMessageStateModel).where(
        *_provider_status_state_predicates(log, provider_status="delivered")
    )

    assert "batch_id" not in str(statement.whereclause)


def test_late_failed_receipt_remains_scoped_to_its_original_batch() -> None:
    log = SimpleNamespace(
        recipient_id=uuid.uuid4(),
        message_type="welcome",
        batch_id=uuid.uuid4(),
    )

    statement = select(WhatsAppRecipientMessageStateModel).where(
        *_provider_status_state_predicates(log, provider_status="failed")
    )

    compiled = statement.compile()
    assert "batch_id" in str(statement.whereclause)
    assert log.batch_id in compiled.params.values()


@pytest.mark.asyncio
async def test_batch_status_reports_ambiguous_outcomes_separately_from_failures() -> None:
    now = datetime.now(tz=UTC)
    stale_time = now.replace(year=now.year - 1)
    rows = [
        (
            SimpleNamespace(
                status="delivery_unknown",
                status_updated_at=now,
                provider_message_id=None,
                error_message="Provider outcome is unknown",
            ),
            SimpleNamespace(id=uuid.uuid4(), normalized_phone_number="+919999999991"),
        ),
        (
            SimpleNamespace(
                status="processing",
                status_updated_at=stale_time,
                provider_message_id=None,
                error_message=None,
            ),
            SimpleNamespace(id=uuid.uuid4(), normalized_phone_number="+919999999992"),
        ),
        (
            SimpleNamespace(
                status="failed",
                status_updated_at=now,
                provider_message_id=None,
                error_message="Recipient number rejected",
            ),
            SimpleNamespace(id=uuid.uuid4(), normalized_phone_number="+919999999993"),
        ),
    ]
    result = MagicMock()
    result.all.return_value = rows
    session = AsyncMock()
    session.execute.return_value = result

    response = await get_broadcast_batch_status(
        batch_id=uuid.uuid4(),
        current_user=SimpleNamespace(role=UserRole.SUPER_ADMIN, agency_id=None),
        session=session,
    )

    assert response.queued == 0
    assert response.sent == 0
    assert response.failed == 1
    assert response.delivery_unknown == 2
    assert [item.status for item in response.results] == [
        "delivery_unknown",
        "stalled",
        "failed",
    ]


def test_manual_recipient_rejects_non_phone_characters_and_excess_digits() -> None:
    for invalid_number in (
        "call-me-9876543210",
        "1234567890123456789012345678901",
    ):
        with pytest.raises(HTTPException) as exc_info:
            _normalized_recipient_inputs(
                [
                    WhatsAppRecipientInput(
                        name="Invalid",
                        phone_number=invalid_number,
                    )
                ]
            )

        assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_excel_contact_upload_enforces_compressed_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp.MAX_WHATSAPP_CONTACT_FILE_BYTES",
        4,
    )
    upload = UploadFile(
        file=BytesIO(b"12345"),
        filename="contacts.xlsx",
    )

    with pytest.raises(HTTPException) as exc_info:
        await _parse_excel_contacts(upload)

    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_excel_contact_upload_detects_headers_below_title_row() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([None, "GC Staff List", None, None])
    sheet.append([None, "S.no", "NAME", "Phone"])
    sheet.append([None, 1, "Aarav Sharma", 9873361557])
    sheet.append([None, 2, "Meera Patel", 9355926411])
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    payload.seek(0)
    upload = UploadFile(file=payload, filename="contacts.xlsx")

    contacts = await _parse_excel_contacts(upload)
    normalized = _normalized_recipient_inputs(contacts)

    assert [(contact.name, contact.phone_number) for contact in contacts] == [
        ("Aarav Sharma", "9873361557"),
        ("Meera Patel", "9355926411"),
    ]
    assert set(normalized) == {
        "+919873361557",
        "+919355926411",
    }


@pytest.mark.asyncio
async def test_excel_contact_upload_distinguishes_contact_name_from_phone() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Contact Name", "Mobile Number"])
    sheet.append(["Aarav Sharma", 9873361557])
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    payload.seek(0)

    contacts = await _parse_excel_contacts(
        UploadFile(file=payload, filename="contacts.xlsx"),
    )

    assert [(contact.name, contact.phone_number) for contact in contacts] == [
        ("Aarav Sharma", "9873361557"),
    ]


@pytest.mark.asyncio
async def test_excel_contact_upload_converts_unexpected_parser_error_to_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp._validate_excel_archive",
        lambda _payload: None,
    )

    def raise_malformed_workbook(*_args: object, **_kwargs: object) -> None:
        raise KeyError("missing OOXML workbook relationship")

    monkeypatch.setattr(
        "app.presentation.api.v1.routes.whatsapp.load_workbook",
        raise_malformed_workbook,
    )

    with pytest.raises(HTTPException) as exc_info:
        await _parse_excel_contacts(
            UploadFile(file=BytesIO(b"malformed"), filename="contacts.xlsx"),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "The uploaded Excel contact file could not be read"


@pytest.mark.asyncio
async def test_excel_contact_preview_returns_named_normalized_recipients() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([None, "GCT Staff Mobile Number Detail", None, None])
    sheet.append([None, "S.no", "NAME", "Phone"])
    sheet.append([None, 1, "  Aarav   Sharma  ", 9873361557])
    sheet.append([None, 2, "Meera Patel", "+91 93559 26411"])
    sheet.append([None, 3, "Duplicate Aarav", "+91-9873361557"])
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    payload.seek(0)

    response = await preview_excel_contacts(
        contacts_file=UploadFile(file=payload, filename="contacts.xlsx"),
        current_user=SimpleNamespace(),
    )

    assert response.model_dump() == {
        "recipient_count": 2,
        "recipients": [
            {
                "name": "Aarav Sharma",
                "phone_number": "+919873361557",
            },
            {
                "name": "Meera Patel",
                "phone_number": "+919355926411",
            },
        ],
    }


def test_excel_contact_preview_rejects_empty_or_unnamed_contacts() -> None:
    with pytest.raises(HTTPException) as empty_error:
        _excel_contact_preview_response([])

    assert empty_error.value.status_code == 400
    assert "No recipients were found" in str(empty_error.value.detail)

    with pytest.raises(HTTPException) as unnamed_error:
        _excel_contact_preview_response(
            [
                WhatsAppRecipientInput(
                    name=None,
                    phone_number="9873361557",
                )
            ]
        )

    assert unnamed_error.value.status_code == 400
    assert "Missing names for 1 contact" in str(unnamed_error.value.detail)


@pytest.mark.asyncio
async def test_excel_contact_preview_rejects_invalid_file_type() -> None:
    upload = UploadFile(
        file=BytesIO(b"name,phone\nAarav,9873361557"),
        filename="contacts.csv",
    )

    with pytest.raises(HTTPException) as exc_info:
        await preview_excel_contacts(
            contacts_file=upload,
            current_user=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Upload an .xlsx or .xlsm contact file"


def test_excel_contact_preview_route_is_role_gated_and_has_stable_contract() -> None:
    route = next(item for item in whatsapp_router.routes if item.path == "/contacts/preview")

    assert route.methods == {"POST"}
    assert route.response_model is WhatsAppContactPreviewResponse
    assert [dependency.call.__name__ for dependency in route.dependant.dependencies] == [
        "_check_role"
    ]


@pytest.mark.asyncio
async def test_excel_contact_upload_stops_after_recipient_row_limit() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Name", "WhatsApp Phone"])
    for index in range(501):
        sheet.append([f"Recipient {index}", f"9190000{index:05d}"])
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    payload.seek(0)
    upload = UploadFile(file=payload, filename="contacts.xlsx")

    with pytest.raises(HTTPException) as exc_info:
        await _parse_excel_contacts(upload)

    assert exc_info.value.status_code == 400
    assert "at most 500 data rows" in str(exc_info.value.detail)
