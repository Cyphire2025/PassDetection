from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from openpyxl import Workbook
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.application.use_cases.whatsapp.recipient_capacity import (
    WhatsAppRecipientCapacityExceeded,
)
from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
)
from app.infrastructure.repositories.whatsapp_recipient_capacity_repository import (
    require_locked_broadcast_recipient_capacity,
)
from app.infrastructure.whatsapp.worker_runtime import (
    WHATSAPP_BATCH_HEARTBEAT_INTERVAL,
    _heartbeat_queued_batch_claims,
)
from app.presentation.api.v1.routes import client_groups
from app.presentation.api.v1.routes import whatsapp as whatsapp_routes
from app.presentation.api.v1.routes.whatsapp import (
    MAX_WHATSAPP_RECIPIENTS,
    WhatsAppRejectedContactResolveRequest,
    WhatsAppSendRequest,
    _lock_removable_broadcast_recipient,
    _parse_excel_contacts,
    add_broadcast_recipients,
    create_broadcast_group,
    resolve_broadcast_rejected_contact,
    send_broadcast_message,
)
from tests.route_dependencies import patch_route_dependency, set_route_dependency


@pytest.fixture(autouse=True)
def _isolate_mobile_passenger_reconciliation(monkeypatch: pytest.MonkeyPatch) -> None:
    set_route_dependency(
        monkeypatch,
        whatsapp_routes,
        "reconcile_mobile_passenger_access_for_broadcast",
        AsyncMock(),
    )
    monkeypatch.setattr(
        client_groups,
        "reconcile_mobile_passenger_access_for_group",
        AsyncMock(),
    )


def _manual_contacts(count: int) -> list[dict[str, str]]:
    return [
        {
            "name": f"Recipient {index}",
            "phone_number": f"+91 90000 {index:05d}",
        }
        for index in range(count)
    ]


def _excel_upload(count: int) -> UploadFile:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Recipients")
    sheet.append(["Name", "WhatsApp Phone"])
    for contact in _manual_contacts(count):
        sheet.append([contact["name"], contact["phone_number"]])
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()
    payload.seek(0)
    return UploadFile(file=payload, filename="contacts.xlsx")


def test_send_request_accepts_1500_recipient_ids_and_rejects_1501() -> None:
    assert MAX_WHATSAPP_RECIPIENTS == 1_500
    recipient_ids = [uuid.UUID(int=index + 1) for index in range(MAX_WHATSAPP_RECIPIENTS + 1)]

    request = WhatsAppSendRequest(
        message_type="reminder",
        recipient_ids=recipient_ids[:MAX_WHATSAPP_RECIPIENTS],
    )
    assert len(request.recipient_ids or []) == MAX_WHATSAPP_RECIPIENTS

    with pytest.raises(ValidationError):
        WhatsAppSendRequest(
            message_type="reminder",
            recipient_ids=recipient_ids,
        )


@pytest.mark.asyncio
async def test_recipient_removal_locks_tenant_parent_before_child() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    recipient_id = uuid.uuid4()
    group = SimpleNamespace(id=group_id, agency_id=agency_id)
    recipient = SimpleNamespace(id=recipient_id, broadcast_group_id=group_id)

    class ScalarResult:
        def __init__(self, value: object) -> None:
            self.value = value

        def scalar_one_or_none(self) -> object:
            return self.value

    class CapturingSession:
        def __init__(self) -> None:
            self.statements: list[object] = []

        async def execute(self, statement: object) -> ScalarResult:
            self.statements.append(statement)
            return ScalarResult(group if len(self.statements) == 1 else recipient)

    session = CapturingSession()
    actor = SimpleNamespace(role=UserRole.AGENCY_ADMIN, agency_id=agency_id)

    locked_group, locked_recipient = await _lock_removable_broadcast_recipient(
        session,  # type: ignore[arg-type]
        group_id=group_id,
        recipient_id=recipient_id,
        current_user=actor,  # type: ignore[arg-type]
    )

    assert locked_group is group
    assert locked_recipient is recipient
    assert len(session.statements) == 2
    group_sql, recipient_sql = (
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).lower()
        for statement in session.statements
    )
    assert "from whatsapp_broadcast_groups" in group_sql
    assert "whatsapp_broadcast_groups.agency_id" in group_sql
    assert "whatsapp_broadcast_recipients" not in group_sql
    assert "for update" in group_sql
    assert "from whatsapp_broadcast_recipients" in recipient_sql
    assert "whatsapp_broadcast_recipients.broadcast_group_id" in recipient_sql
    assert "whatsapp_broadcast_recipients.agency_id" in recipient_sql
    assert "for update" in recipient_sql


@pytest.mark.asyncio
async def test_send_rejects_legacy_group_with_more_than_1500_active_recipients() -> None:
    agency_id = uuid.uuid4()
    group = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        recipient_opt_in_confirmed_at=datetime.now(tz=UTC),
    )
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    session = MagicMock()
    session.execute = AsyncMock(return_value=group_result)
    recipients = [SimpleNamespace(id=uuid.uuid4()) for _ in range(MAX_WHATSAPP_RECIPIENTS + 1)]
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN,
    )

    with patch_route_dependency(
        "app.presentation.api.v1.routes.whatsapp._group_recipients",
        new=AsyncMock(return_value=recipients),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await send_broadcast_message(
                group_id=group.id,
                body=WhatsAppSendRequest(message_type="reminder"),
                current_user=current_user,
                session=session,
            )

    assert exc_info.value.status_code == 400
    assert "maximum of 1500" in str(exc_info.value.detail)
    statement = session.execute.await_args_list[0].args[0]
    assert "FOR UPDATE" in str(statement)


@pytest.mark.asyncio
async def test_excel_import_accepts_1500_recipients_and_rejects_1501() -> None:
    contacts = await _parse_excel_contacts(_excel_upload(MAX_WHATSAPP_RECIPIENTS))
    assert len(contacts) == MAX_WHATSAPP_RECIPIENTS

    with pytest.raises(HTTPException) as exc_info:
        await _parse_excel_contacts(_excel_upload(MAX_WHATSAPP_RECIPIENTS + 1))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == ("The Excel contact file can contain at most 1500 recipients")


@pytest.mark.asyncio
async def test_create_group_accepts_1500_manual_recipients_and_rejects_1501() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        role=UserRole.AGENCY_ADMIN,
    )
    actor = SimpleNamespace(id=current_user.id, agency_id=current_user.agency_id)

    async def return_group(_session: object, group: object) -> object:
        return group

    with (
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._group_detail",
            new=AsyncMock(side_effect=return_group),
        ),
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._lock_active_whatsapp_actor",
            new=AsyncMock(return_value=actor),
        ),
    ):
        await create_broadcast_group(
            name="Capacity boundary",
            organizing_company_name="Global Connect",
            contacts_json=json.dumps(_manual_contacts(MAX_WHATSAPP_RECIPIENTS)),
            rejected_contacts_json="[]",
            support_contacts_json=json.dumps(
                [{"name": "Support", "phone_number": "+91 99999 99999"}]
            ),
            recipient_opt_in_confirmed=True,
            contacts_file=None,
            current_user=current_user,
            session=session,
        )

    persisted_recipients = [
        call.args[0]
        for call in session.add.call_args_list
        if isinstance(call.args[0], WhatsAppBroadcastRecipientModel)
    ]
    assert len(persisted_recipients) == MAX_WHATSAPP_RECIPIENTS

    rejected_session = MagicMock()
    rejected_session.flush = AsyncMock()
    rejected_session.rollback = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await create_broadcast_group(
            name="Over capacity",
            organizing_company_name="Global Connect",
            contacts_json=json.dumps(_manual_contacts(MAX_WHATSAPP_RECIPIENTS + 1)),
            rejected_contacts_json="[]",
            support_contacts_json=json.dumps(
                [{"name": "Support", "phone_number": "+91 99999 99999"}]
            ),
            recipient_opt_in_confirmed=True,
            contacts_file=None,
            current_user=current_user,
            session=rejected_session,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "A WhatsApp list can contain at most 1500 recipients"
    rejected_session.add.assert_not_called()


@pytest.mark.asyncio
async def test_add_recipients_rejects_aggregate_count_above_1500() -> None:
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    existing_result = MagicMock()
    existing_result.scalars.return_value.all.return_value = [
        SimpleNamespace(
            normalized_phone_number=f"+9180000{index:05d}",
            removed_at=None,
        )
        for index in range(MAX_WHATSAPP_RECIPIENTS - 1)
    ]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[group_result, existing_result])
    session.rollback = AsyncMock()
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        role=UserRole.SUPER_ADMIN,
        agency_id=None,
    )

    with (
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._lock_active_whatsapp_actor",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    id=current_user.id,
                    role=UserRole.SUPER_ADMIN.value,
                    agency_id=None,
                )
            ),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await add_broadcast_recipients(
            group_id=group.id,
            contacts_json=json.dumps(_manual_contacts(2)),
            rejected_contacts_json="[]",
            recipient_opt_in_confirmed=True,
            contacts_file=None,
            current_user=current_user,
            session=session,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "A WhatsApp list can contain at most 1500 recipients"


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _capacity_result(active_by_broadcast: dict[uuid.UUID, int]) -> MagicMock:
    result = MagicMock()
    result.all.return_value = list(active_by_broadcast.items())
    return result


@pytest.mark.asyncio
async def test_capacity_repository_counts_only_active_rows_in_locked_tenant_scope() -> None:
    broadcast_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=_capacity_result({broadcast_id: MAX_WHATSAPP_RECIPIENTS - 1})
    )

    projected = await require_locked_broadcast_recipient_capacity(
        session,
        agency_id=agency_id,
        locked_broadcast_ids=[broadcast_id],
        activating_by_broadcast={broadcast_id: 1},
    )

    assert projected == {broadcast_id: MAX_WHATSAPP_RECIPIENTS}
    statement = session.execute.await_args.args[0]
    sql = str(statement).lower()
    parameters = list(statement.compile().params.values())
    assert "group by" in sql
    assert "whatsapp_broadcast_recipients.agency_id" in sql
    assert "whatsapp_broadcast_recipients.removed_at is null" in sql
    assert agency_id in parameters
    assert broadcast_id in next(value for value in parameters if isinstance(value, list))

    with pytest.raises(RuntimeError, match="requires locked broadcast rows"):
        await require_locked_broadcast_recipient_capacity(
            session,
            agency_id=agency_id,
            locked_broadcast_ids=[],
            activating_by_broadcast={broadcast_id: 1},
        )


@pytest.mark.asyncio
async def test_capacity_repository_rejects_1501_before_mutation() -> None:
    broadcast_id = uuid.uuid4()
    session = MagicMock()
    session.execute = AsyncMock(
        return_value=_capacity_result({broadcast_id: MAX_WHATSAPP_RECIPIENTS})
    )

    with pytest.raises(WhatsAppRecipientCapacityExceeded) as exc_info:
        await require_locked_broadcast_recipient_capacity(
            session,
            agency_id=uuid.uuid4(),
            locked_broadcast_ids=[broadcast_id],
            activating_by_broadcast={broadcast_id: 1},
        )

    assert exc_info.value.active_count == MAX_WHATSAPP_RECIPIENTS
    assert exc_info.value.projected_count == MAX_WHATSAPP_RECIPIENTS + 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("active_count", "should_succeed"),
    [(MAX_WHATSAPP_RECIPIENTS - 1, True), (MAX_WHATSAPP_RECIPIENTS, False)],
)
async def test_rejected_contact_reactivation_enforces_1500_boundary(
    active_count: int,
    should_succeed: bool,
) -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    group = SimpleNamespace(
        id=group_id,
        agency_id=agency_id,
        recipient_opt_in_confirmed_at=now,
        updated_at=now,
    )
    rejected = WhatsAppBroadcastRejectedContactModel(
        id=uuid.uuid4(),
        broadcast_group_id=group_id,
        agency_id=agency_id,
        source_file_name="contacts.xlsx",
        sheet_name="Sheet1",
        row_number=2,
        raw_name="Corrected",
        raw_phone_number="9876543210",
        imported_fields={},
        reason_code="invalid_phone",
        reason="Invalid phone",
        fingerprint="a" * 64,
        display_order=1,
        created_at=now,
    )
    recipient = SimpleNamespace(
        id=uuid.uuid4(),
        removed_at=now,
        suppressed_by_roster_resolution_id=None,
        display_order=1,
        name="Old",
        phone_number="9876543210",
        imported_fields={},
    )
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result(group),
            _scalar_result(rejected),
            _scalar_result(recipient),
            _capacity_result({group_id: active_count}),
            MagicMock(),
            MagicMock(),
        ]
    )
    session.flush = AsyncMock()

    call = resolve_broadcast_rejected_contact(
        group_id=group_id,
        rejected_contact_id=rejected.id,
        body=WhatsAppRejectedContactResolveRequest(
            name="Corrected Recipient",
            phone_number="9876543210",
            recipient_opt_in_confirmed=True,
        ),
        current_user=SimpleNamespace(
            id=uuid.uuid4(),
            role=UserRole.SUPER_ADMIN,
            agency_id=None,
        ),
        session=session,
    )
    with (
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._group_detail",
            new=AsyncMock(return_value=group),
        ),
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp.suppress_active_replacement_recipients",
            new=AsyncMock(),
        ),
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._prepare_private_recipient_mutation",
            new=AsyncMock(),
        ),
    ):
        if should_succeed:
            assert await call is group
            assert recipient.removed_at is None
            assert recipient.name == "Corrected Recipient"
            assert session.execute.await_count == 6
        else:
            with pytest.raises(HTTPException) as exc_info:
                await call
            assert exc_info.value.status_code == 400
            assert "maximum of 1500" in str(exc_info.value.detail)
            assert recipient.removed_at == now
            assert recipient.name == "Old"
            assert session.execute.await_count == 4
            session.flush.assert_not_awaited()


def _replacement_resolution(*, agency_id: uuid.UUID, group_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        client_group_id=group_id,
        submission_id=uuid.uuid4(),
        broadcast_recipient_id=uuid.uuid4(),
        resolution_type="replacement",
        status="active",
        suppressed_recipient_ids=[],
        excluded_submission_ids=[],
        created_at=datetime.now(tz=UTC),
        restored_by_user_id=None,
        restored_at=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("overflow", [False, True])
async def test_multi_group_restore_is_atomic_at_1500_boundary(overflow: bool) -> None:
    agency_id = uuid.uuid4()
    client_group_id = uuid.uuid4()
    broadcast_ids = sorted([uuid.uuid4(), uuid.uuid4()], key=str)
    resolution = _replacement_resolution(agency_id=agency_id, group_id=client_group_id)
    group = SimpleNamespace(id=client_group_id, agency_id=agency_id)
    removed_at = datetime.now(tz=UTC)
    recipients = [
        SimpleNamespace(
            id=uuid.uuid4(),
            broadcast_group_id=broadcast_id,
            removed_at=removed_at,
            suppressed_by_roster_resolution_id=resolution.id,
        )
        for broadcast_id in broadcast_ids
    ]
    active_counts = {
        broadcast_ids[0]: MAX_WHATSAPP_RECIPIENTS if overflow else MAX_WHATSAPP_RECIPIENTS - 1,
        broadcast_ids[1]: MAX_WHATSAPP_RECIPIENTS - 1,
    }
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            _scalar_result(resolution),
            _scalars_result(broadcast_ids),
            _scalar_result(resolution),
            _scalars_result(recipients),
            _capacity_result(active_counts),
            MagicMock(),
        ]
    )
    session.flush = AsyncMock()
    current_user = SimpleNamespace(id=uuid.uuid4(), email="admin@example.com")
    audit_repository = SimpleNamespace(record=AsyncMock())

    with (
        patch.object(client_groups, "_require_whatsapp_broadcast_access"),
        patch.object(
            client_groups,
            "_require_managed_group",
            new=AsyncMock(return_value=group),
        ),
        patch.object(
            client_groups,
            "lock_whatsapp_broadcast_groups",
            new=AsyncMock(return_value=broadcast_ids),
        ),
        patch.object(
            client_groups,
            "suppress_active_replacement_recipients",
            new=AsyncMock(return_value=[]),
        ),
        patch.object(
            client_groups,
            "AuditLogRepository",
            return_value=audit_repository,
        ),
    ):
        call = client_groups.restore_roster_resolution(
            link_id=client_group_id,
            resolution_id=resolution.id,
            current_user=current_user,
            session=session,
            _csrf=None,
        )
        if not overflow:
            response = await call
            assert response.status == "restored"
            assert all(recipient.removed_at is None for recipient in recipients)
            assert all(
                recipient.suppressed_by_roster_resolution_id is None for recipient in recipients
            )
            assert session.execute.await_count == 6
        else:
            with pytest.raises(HTTPException) as exc_info:
                await call
            assert exc_info.value.status_code == 400
            assert "maximum of 1500" in str(exc_info.value.detail)
            assert all(recipient.removed_at == removed_at for recipient in recipients)
            assert all(
                recipient.suppressed_by_roster_resolution_id == resolution.id
                for recipient in recipients
            )
            assert resolution.status == "active"
            assert session.execute.await_count == 5
            session.flush.assert_not_awaited()
            audit_repository.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_large_batch_heartbeat_refreshes_only_its_queued_claims() -> None:
    session = AsyncMock()
    batch_id = uuid.uuid4()
    heartbeat_at = datetime.now(tz=UTC)

    await _heartbeat_queued_batch_claims(
        session,
        batch_id=batch_id,
        heartbeat_at=heartbeat_at,
    )

    assert WHATSAPP_BATCH_HEARTBEAT_INTERVAL.total_seconds() == 5 * 60
    assert session.execute.await_count == 2
    log_statement = session.execute.await_args_list[0].args[0]
    state_statement = session.execute.await_args_list[1].args[0]
    assert "whatsapp_message_logs.batch_id" in str(log_statement)
    assert "whatsapp_message_logs.status" in str(log_statement)
    assert "whatsapp_recipient_message_states.batch_id" in str(state_statement)
    assert "whatsapp_recipient_message_states.status" in str(state_statement)
    for statement in (log_statement, state_statement):
        parameter_values = statement.compile().params.values()
        assert batch_id in parameter_values
        assert "queued" in parameter_values
        assert heartbeat_at in parameter_values
    session.commit.assert_awaited_once()
