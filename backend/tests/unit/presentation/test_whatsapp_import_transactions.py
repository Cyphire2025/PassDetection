from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes import whatsapp as whatsapp_routes
from app.presentation.api.v1.routes.whatsapp import (
    WhatsAppRecipientInput,
    _lock_active_whatsapp_actor,
    add_broadcast_recipients,
    create_broadcast_group,
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


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values: list[object]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


@pytest.mark.asyncio
async def test_actor_reauthorization_locks_active_user_and_agency_scope() -> None:
    agency_id = uuid.uuid4()
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN,
    )
    actor = SimpleNamespace(
        id=current_user.id,
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN.value,
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=_scalar_result(actor))

    assert (
        await _lock_active_whatsapp_actor(
            session,
            current_user=current_user,
            require_agency=True,
        )
        is actor
    )

    statement = session.execute.await_args.args[0]
    sql = str(statement).lower()
    params = statement.compile().params.values()
    assert "join agencies" in sql
    assert "for update" in sql
    assert "users.is_active is true" in sql
    assert "users.deleted_at is null" in sql
    assert "agencies.is_active is true" in sql
    assert current_user.id in params
    assert agency_id in params
    assert UserRole.AGENCY_ADMIN.value in params


@pytest.mark.asyncio
async def test_create_group_parses_workbook_before_reauthorization_and_mutation() -> None:
    events: list[str] = []
    agency_id = uuid.uuid4()
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN,
    )
    actor = SimpleNamespace(id=current_user.id, agency_id=agency_id)
    session = MagicMock()

    async def rollback() -> None:
        events.append("rollback_auth_transaction")

    async def parse_contacts(_upload: object) -> list[WhatsAppRecipientInput]:
        events.append("parse_workbook")
        return [WhatsAppRecipientInput(name="Aarav", phone_number="9876543210")]

    async def lock_actor(*_args: object, **_kwargs: object) -> object:
        events.append("reauthorize_actor")
        return actor

    def add_model(_model: object) -> None:
        events.append("mutate_roster")

    session.rollback = AsyncMock(side_effect=rollback)
    session.flush = AsyncMock()
    session.add = MagicMock(side_effect=add_model)

    async def return_group(_session: object, group: object) -> object:
        return group

    with (
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._parse_excel_contacts",
            new=AsyncMock(side_effect=parse_contacts),
        ),
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._lock_active_whatsapp_actor",
            new=AsyncMock(side_effect=lock_actor),
        ),
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._group_detail",
            new=AsyncMock(side_effect=return_group),
        ),
    ):
        await create_broadcast_group(
            name="Imported group",
            organizing_company_name="Global Connect",
            contacts_json="[]",
            rejected_contacts_json="[]",
            support_contacts_json=json.dumps([{"name": "Support", "phone_number": "9876543211"}]),
            recipient_opt_in_confirmed=True,
            contacts_file=MagicMock(),
            current_user=current_user,
            session=session,
        )

    assert events[:3] == [
        "rollback_auth_transaction",
        "parse_workbook",
        "reauthorize_actor",
    ]
    assert events.index("reauthorize_actor") < events.index("mutate_roster")


@pytest.mark.asyncio
async def test_add_recipients_parses_before_tenant_group_lock() -> None:
    events: list[str] = []
    agency_id = uuid.uuid4()
    group = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        recipient_opt_in_confirmed_at=None,
        updated_at=None,
    )
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN,
    )
    actor = SimpleNamespace(
        id=current_user.id,
        agency_id=agency_id,
        role=UserRole.AGENCY_ADMIN.value,
    )
    query_results = iter([_scalar_result(group), _scalars_result([])])
    session = MagicMock()

    async def rollback() -> None:
        events.append("rollback_auth_transaction")

    async def parse_contacts(_upload: object) -> list[WhatsAppRecipientInput]:
        events.append("parse_workbook")
        return [WhatsAppRecipientInput(name="Aarav", phone_number="9876543210")]

    async def lock_actor(*_args: object, **_kwargs: object) -> object:
        events.append("reauthorize_actor")
        return actor

    async def execute(_statement: object) -> object:
        events.append("database_query")
        return next(query_results)

    session.rollback = AsyncMock(side_effect=rollback)
    session.execute = AsyncMock(side_effect=execute)
    session.flush = AsyncMock()

    with (
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._parse_excel_contacts",
            new=AsyncMock(side_effect=parse_contacts),
        ),
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._lock_active_whatsapp_actor",
            new=AsyncMock(side_effect=lock_actor),
        ),
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._next_roster_display_order",
            new=AsyncMock(return_value=1),
        ),
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp.suppress_active_replacement_recipients",
            new=AsyncMock(),
        ),
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._prepare_private_recipient_mutation",
            new=AsyncMock(),
        ),
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._group_detail",
            new=AsyncMock(return_value=group),
        ),
    ):
        await add_broadcast_recipients(
            group_id=group.id,
            contacts_json="[]",
            rejected_contacts_json="[]",
            recipient_opt_in_confirmed=True,
            contacts_file=MagicMock(),
            current_user=current_user,
            session=session,
        )

    assert events[:4] == [
        "rollback_auth_transaction",
        "parse_workbook",
        "reauthorize_actor",
        "database_query",
    ]
    group_statement = session.execute.await_args_list[0].args[0]
    sql = str(group_statement).lower()
    params = group_statement.compile().params.values()
    assert "join agencies" in sql
    assert "agencies.is_active is true" in sql
    assert "for update" in sql
    assert agency_id in params


@pytest.mark.asyncio
async def test_create_group_rejects_revoked_actor_after_parsing_before_mutation() -> None:
    events: list[str] = []
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        role=UserRole.AGENCY_MANAGER,
    )
    session = MagicMock()

    async def rollback() -> None:
        events.append("rollback_auth_transaction")

    async def parse_contacts(_upload: object) -> list[WhatsAppRecipientInput]:
        events.append("parse_workbook")
        return [WhatsAppRecipientInput(name="Aarav", phone_number="9876543210")]

    async def execute(_statement: object) -> MagicMock:
        events.append("reauthorize_actor")
        return _scalar_result(None)

    session.rollback = AsyncMock(side_effect=rollback)
    session.execute = AsyncMock(side_effect=execute)
    session.flush = AsyncMock()

    with (
        patch_route_dependency(
            "app.presentation.api.v1.routes.whatsapp._parse_excel_contacts",
            new=AsyncMock(side_effect=parse_contacts),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await create_broadcast_group(
            name="Imported group",
            organizing_company_name="Global Connect",
            contacts_json="[]",
            rejected_contacts_json="[]",
            support_contacts_json=json.dumps([{"name": "Support", "phone_number": "9876543211"}]),
            recipient_opt_in_confirmed=True,
            contacts_file=MagicMock(),
            current_user=current_user,
            session=session,
        )

    assert exc_info.value.status_code == 403
    assert events == [
        "rollback_auth_transaction",
        "parse_workbook",
        "reauthorize_actor",
    ]
    session.add.assert_not_called()
