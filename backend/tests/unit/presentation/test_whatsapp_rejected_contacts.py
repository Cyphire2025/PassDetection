from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import UniqueConstraint

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
)
from app.presentation.api.v1.routes import whatsapp as whatsapp_routes
from app.presentation.api.v1.routes.whatsapp import (
    _WHATSAPP_CONTACT_REJECTION_REASONS,
    WhatsAppRejectedContactResolveRequest,
    _parse_rejected_contacts,
    _rejected_contact_fingerprint,
    add_broadcast_recipients,
    create_broadcast_group,
    list_broadcast_rejected_contacts,
    resolve_broadcast_rejected_contact,
)


@pytest.fixture(autouse=True)
def _isolate_mobile_passenger_reconciliation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        whatsapp_routes,
        "reconcile_mobile_passenger_access_for_broadcast",
        AsyncMock(),
    )


def _rejected_json(*, source_file_name: str = "Saigon Sheet.xlsx") -> str:
    return json.dumps(
        [
            {
                "source_file_name": source_file_name,
                "sheet_name": "Sheet1",
                "row_number": 14,
                "raw_name": "Rejected Contact",
                "raw_phone_number": "919726092",
                "imported_fields": {
                    "email": "rejected@example.com",
                    "staff_code": "GC-14",
                },
                "reason_code": "invalid_phone",
                "reason": "Client-supplied text must not be stored.",
            }
        ]
    )


def test_rejected_contact_schema_is_non_sendable_and_cascade_scoped() -> None:
    table = WhatsAppBroadcastRejectedContactModel.__table__
    group_fk = next(
        foreign_key
        for foreign_key in table.foreign_keys
        if foreign_key.target_fullname == "whatsapp_broadcast_groups.id"
    )
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert group_fk.ondelete == "CASCADE"
    assert ("broadcast_group_id", "fingerprint") in unique_columns
    assert table.name != WhatsAppBroadcastRecipientModel.__table__.name
    assert "normalized_phone_number" not in table.c


@pytest.mark.asyncio
async def test_create_group_persists_rejected_only_without_opt_in() -> None:
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
        patch(
            "app.presentation.api.v1.routes.whatsapp._group_detail",
            new=AsyncMock(side_effect=return_group),
        ),
        patch(
            "app.presentation.api.v1.routes.whatsapp._lock_active_whatsapp_actor",
            new=AsyncMock(return_value=actor),
        ),
    ):
        group = await create_broadcast_group(
            name="Rejected import review",
            organizing_company_name="Global Connect",
            contacts_json="[]",
            rejected_contacts_json=_rejected_json(source_file_name=r"C:\uploads\Saigon Sheet.xlsx"),
            support_contacts_json=json.dumps([{"name": "Support", "phone_number": "9876543210"}]),
            recipient_opt_in_confirmed=False,
            contacts_file=None,
            current_user=current_user,
            session=session,
        )

    added = [call.args[0] for call in session.add.call_args_list]
    rejected = next(
        model for model in added if isinstance(model, WhatsAppBroadcastRejectedContactModel)
    )
    assert group.recipient_opt_in_confirmed_at is None
    assert not any(isinstance(model, WhatsAppBroadcastRecipientModel) for model in added)
    assert rejected.source_file_name == "Saigon Sheet.xlsx"
    assert rejected.imported_fields == {
        "email": "rejected@example.com",
        "staff_code": "GC-14",
    }
    assert rejected.reason == _WHATSAPP_CONTACT_REJECTION_REASONS["invalid_phone"]
    assert rejected.reason != "Client-supplied text must not be stored."


@pytest.mark.asyncio
async def test_add_rejected_only_deduplicates_existing_fingerprint() -> None:
    group = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        recipient_opt_in_confirmed_at=None,
        updated_at=datetime.now(tz=UTC),
    )
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    existing_rejected_result = MagicMock()
    existing_contact = _parse_rejected_contacts(_rejected_json())[0]
    existing_model = WhatsAppBroadcastRejectedContactModel(
        fingerprint=_rejected_contact_fingerprint(existing_contact),
        imported_fields={},
    )
    existing_rejected_result.scalars.return_value.all.return_value = [existing_model]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[group_result, existing_rejected_result])
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    current_user = SimpleNamespace(
        id=uuid.uuid4(),
        role=UserRole.SUPER_ADMIN,
        agency_id=None,
    )

    with (
        patch(
            "app.presentation.api.v1.routes.whatsapp._group_detail",
            new=AsyncMock(return_value=group),
        ),
        patch(
            "app.presentation.api.v1.routes.whatsapp._lock_active_whatsapp_actor",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    id=current_user.id,
                    role=UserRole.SUPER_ADMIN.value,
                    agency_id=None,
                )
            ),
        ),
    ):
        await add_broadcast_recipients(
            group_id=group.id,
            contacts_json="[]",
            rejected_contacts_json=_rejected_json(),
            recipient_opt_in_confirmed=False,
            contacts_file=None,
            current_user=current_user,
            session=session,
        )

    added = [call.args[0] for call in session.add.call_args_list]
    assert not any(isinstance(model, WhatsAppBroadcastRejectedContactModel) for model in added)
    assert existing_model.imported_fields == {
        "email": "rejected@example.com",
        "staff_code": "GC-14",
    }
    assert group.recipient_opt_in_confirmed_at is None


@pytest.mark.asyncio
async def test_create_group_persists_sendable_and_rejected_contacts_together() -> None:
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
        patch(
            "app.presentation.api.v1.routes.whatsapp._group_detail",
            new=AsyncMock(side_effect=return_group),
        ),
        patch(
            "app.presentation.api.v1.routes.whatsapp._lock_active_whatsapp_actor",
            new=AsyncMock(return_value=actor),
        ),
    ):
        group = await create_broadcast_group(
            name="Mixed import",
            organizing_company_name="Global Connect",
            contacts_json=json.dumps([{"name": "Accepted Contact", "phone_number": "9876543212"}]),
            rejected_contacts_json=_rejected_json(),
            support_contacts_json=json.dumps([{"name": "Support", "phone_number": "9876543210"}]),
            recipient_opt_in_confirmed=True,
            contacts_file=None,
            current_user=current_user,
            session=session,
        )

    added = [call.args[0] for call in session.add.call_args_list]
    assert any(isinstance(model, WhatsAppBroadcastRecipientModel) for model in added)
    assert any(isinstance(model, WhatsAppBroadcastRejectedContactModel) for model in added)
    assert group.recipient_opt_in_confirmed_at is not None
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_rejected_contact_list_is_paginated_and_agency_scoped() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group_id
    total_result = MagicMock()
    total_result.scalar_one.return_value = 1
    model = WhatsAppBroadcastRejectedContactModel(
        id=uuid.uuid4(),
        broadcast_group_id=group_id,
        agency_id=agency_id,
        source_file_name="Saigon Sheet.xlsx",
        sheet_name="Sheet1",
        row_number=14,
        raw_name="Rejected Contact",
        raw_phone_number="919726092",
        imported_fields={"email": "rejected@example.com"},
        reason_code="invalid_phone",
        reason=_WHATSAPP_CONTACT_REJECTION_REASONS["invalid_phone"],
        fingerprint="a" * 64,
        created_at=datetime.now(tz=UTC),
    )
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = [model]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[group_result, total_result, items_result])

    response = await list_broadcast_rejected_contacts(
        group_id=group_id,
        limit=25,
        offset=0,
        current_user=SimpleNamespace(
            id=uuid.uuid4(),
            role=UserRole.AGENCY_ADMIN,
            agency_id=agency_id,
        ),
        session=session,
    )

    group_query = session.execute.await_args_list[0].args[0]
    assert agency_id in group_query.compile().params.values()
    assert response.total == 1
    assert response.limit == 25
    assert response.offset == 0
    assert response.items[0].row_number == 14
    assert response.items[0].reason_code == "invalid_phone"
    assert response.items[0].imported_fields == {"email": "rejected@example.com"}


@pytest.mark.asyncio
async def test_corrected_rejected_contact_becomes_unsent_valid_recipient() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    rejected_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    group = SimpleNamespace(
        id=group_id,
        agency_id=agency_id,
        recipient_opt_in_confirmed_at=now,
        updated_at=now,
    )
    rejected = WhatsAppBroadcastRejectedContactModel(
        id=rejected_id,
        broadcast_group_id=group_id,
        agency_id=agency_id,
        source_file_name="Saigon Sheet.xlsx",
        sheet_name="Sheet1",
        row_number=14,
        raw_name="Rejected Contact",
        raw_phone_number="919726092",
        imported_fields={
            "email": "rejected@example.com",
            "staff_code": "GC-14",
        },
        reason_code="invalid_phone",
        reason=_WHATSAPP_CONTACT_REJECTION_REASONS["invalid_phone"],
        fingerprint="b" * 64,
        display_order=7,
        created_at=now,
    )
    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    rejected_result = MagicMock()
    rejected_result.scalar_one_or_none.return_value = rejected
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    count_result = MagicMock()
    count_result.scalar_one.return_value = 12
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            group_result,
            rejected_result,
            existing_result,
            count_result,
            MagicMock(),
        ]
    )
    session.flush = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.whatsapp._group_detail",
            new=AsyncMock(return_value=group),
        ),
        patch(
            "app.presentation.api.v1.routes.whatsapp.suppress_active_replacement_recipients",
            new=AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.whatsapp._prepare_private_recipient_mutation",
            new=AsyncMock(),
        ),
    ):
        response = await resolve_broadcast_rejected_contact(
            group_id=group_id,
            rejected_contact_id=rejected_id,
            body=WhatsAppRejectedContactResolveRequest(
                name="Corrected Contact",
                phone_number="9876543211",
                recipient_opt_in_confirmed=True,
            ),
            current_user=SimpleNamespace(
                id=uuid.uuid4(),
                role=UserRole.SUPER_ADMIN,
                agency_id=None,
            ),
            session=session,
        )

    added = [call.args[0] for call in session.add.call_args_list]
    recipient = next(model for model in added if isinstance(model, WhatsAppBroadcastRecipientModel))
    assert response is group
    assert recipient.name == "Corrected Contact"
    assert recipient.normalized_phone_number == "+919876543211"
    assert recipient.display_order == 7
    assert recipient.imported_fields["source_row"] == "14"
    assert recipient.imported_fields["email"] == "rejected@example.com"
    assert recipient.imported_fields["staff_code"] == "GC-14"
