from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    ManagerGroupAccessModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.presentation.api.v1.routes import client_groups as client_group_routes
from app.presentation.api.v1.routes.client_groups import (
    _replace_whatsapp_links,
    _validate_broadcast_ids,
    get_client_group_whatsapp_links,
    get_client_group_whatsapp_matches,
    list_whatsapp_broadcast_options_for_group,
    replace_client_group_whatsapp_links,
    router,
    update_client_group,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    ClientGroupResponse,
    CreateClientGroupRequest,
    ReplaceWhatsAppBroadcastLinksRequest,
    UpdateClientGroupRequest,
)

NOW = datetime(2026, 7, 20, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_mobile_passenger_reconciliation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        client_group_routes,
        "reconcile_mobile_passenger_access_for_group",
        AsyncMock(),
    )


def _domain_user(
    user_id: uuid.UUID,
    agency_id: uuid.UUID,
    *,
    email: str,
) -> User:
    return User(
        id=user_id,
        email=email,
        hashed_password="unused",
        full_name=email,
        role=UserRole.AGENCY_MANAGER,
        agency_id=agency_id,
    )


async def _seed(db_session: AsyncSession) -> dict[str, object]:
    agency_id = uuid.uuid4()
    other_agency_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    viewer_id = uuid.uuid4()
    db_session.add_all(
        [
            AgencyModel(
                id=agency_id,
                name="Agency",
                email=f"{agency_id}@example.test",
            ),
            AgencyModel(
                id=other_agency_id,
                name="Other",
                email=f"{other_agency_id}@example.test",
            ),
            UserModel(
                id=creator_id,
                email="creator@example.test",
                hashed_password="unused",
                full_name="Creator",
                role=UserRole.AGENCY_MANAGER.value,
                agency_id=agency_id,
            ),
            UserModel(
                id=viewer_id,
                email="viewer@example.test",
                hashed_password="unused",
                full_name="Viewer",
                role=UserRole.AGENCY_MANAGER.value,
                agency_id=agency_id,
            ),
        ]
    )
    group_id = uuid.uuid4()
    group = ClientGroupModel(
        id=group_id,
        name="Trip",
        token=f"token-{group_id}",
        agency_id=agency_id,
        status="active",
        created_by_user_id=creator_id,
        created_at=NOW,
        departure_cities=[],
    )
    first_broadcast = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        name="North",
        organizing_company_name="Agency",
        created_by_user_id=creator_id,
        created_at=NOW,
        updated_at=NOW,
    )
    second_broadcast = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        name="South",
        organizing_company_name="Agency",
        created_by_user_id=creator_id,
        created_at=NOW,
        updated_at=NOW,
    )
    third_broadcast = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        name="West",
        organizing_company_name="Agency",
        created_by_user_id=creator_id,
        created_at=NOW,
        updated_at=NOW,
    )
    other_broadcast = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(),
        agency_id=other_agency_id,
        name="Other tenant",
        organizing_company_name="Other",
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add_all(
        [
            group,
            first_broadcast,
            second_broadcast,
            third_broadcast,
            other_broadcast,
            ManagerGroupAccessModel(
                id=uuid.uuid4(),
                manager_id=viewer_id,
                group_id=group_id,
                agency_id=agency_id,
                created_at=NOW,
            ),
            ClientGroupWhatsAppBroadcastLinkModel(
                id=uuid.uuid4(),
                client_group_id=group_id,
                broadcast_group_id=first_broadcast.id,
                agency_id=agency_id,
                created_by_user_id=creator_id,
                created_at=NOW,
            ),
            ClientGroupWhatsAppBroadcastLinkModel(
                id=uuid.uuid4(),
                client_group_id=group_id,
                broadcast_group_id=second_broadcast.id,
                agency_id=agency_id,
                created_by_user_id=creator_id,
                created_at=NOW,
            ),
            WhatsAppBroadcastRecipientModel(
                id=uuid.uuid4(),
                broadcast_group_id=first_broadcast.id,
                agency_id=agency_id,
                name="Passenger",
                phone_number="9876543210",
                normalized_phone_number="+919876543210",
                created_at=NOW,
            ),
            WhatsAppBroadcastRecipientModel(
                id=uuid.uuid4(),
                broadcast_group_id=second_broadcast.id,
                agency_id=agency_id,
                name="Passenger duplicate provenance",
                phone_number="+919876543210",
                normalized_phone_number="+919876543210",
                created_at=NOW,
            ),
            WhatsAppBroadcastRecipientModel(
                id=uuid.uuid4(),
                broadcast_group_id=second_broadcast.id,
                agency_id=agency_id,
                name="Removed",
                phone_number="9123456789",
                normalized_phone_number="+919123456789",
                removed_at=NOW,
                created_at=NOW,
            ),
        ]
    )
    await db_session.flush()
    return {
        "agency_id": agency_id,
        "creator": _domain_user(creator_id, agency_id, email="creator@example.test"),
        "viewer": _domain_user(viewer_id, agency_id, email="viewer@example.test"),
        "group": group,
        "broadcasts": [
            first_broadcast,
            second_broadcast,
            third_broadcast,
        ],
        "other_broadcast": other_broadcast,
    }


@pytest.mark.asyncio
async def test_same_agency_manager_can_manage_links_and_read_matches(
    db_session: AsyncSession,
) -> None:
    seeded = await _seed(db_session)
    group = seeded["group"]
    viewer = seeded["viewer"]

    links = await get_client_group_whatsapp_links(
        group.id,
        current_user=viewer,
        session=db_session,
    )
    matches = await get_client_group_whatsapp_matches(
        group.id,
        broadcast_id=None,
        match_status="all",
        sort_by="name",
        sort_order="asc",
        page=1,
        page_size=100,
        current_user=viewer,
        session=db_session,
    )

    assert links.can_manage is True
    assert links.broadcast_count == 2
    assert links.recipient_count == 1
    assert matches.counts.total_recipients == 1
    assert matches.counts.not_submitted_count == 1
    assert matches.total == 1
    assert len(matches.matches[0].recipient_ids) == 2

    options = await list_whatsapp_broadcast_options_for_group(
        group.id,
        current_user=viewer,
        session=db_session,
    )
    assert {option.id for option in options} == {broadcast.id for broadcast in seeded["broadcasts"]}

    replacement = await replace_client_group_whatsapp_links(
        group.id,
        ReplaceWhatsAppBroadcastLinksRequest(whatsapp_broadcast_group_ids=[]),
        current_user=viewer,
        session=db_session,
    )
    assert replacement.can_manage is True
    assert replacement.broadcast_count == 0


@pytest.mark.asyncio
async def test_matches_can_filter_by_a_linked_broadcast_and_reject_unlinked(
    db_session: AsyncSession,
) -> None:
    seeded = await _seed(db_session)
    group = seeded["group"]
    viewer = seeded["viewer"]
    first, second, unlinked = seeded["broadcasts"]
    other_tenant = seeded["other_broadcast"]
    db_session.add(
        WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(),
            broadcast_group_id=second.id,
            agency_id=seeded["agency_id"],
            name="South only",
            phone_number="9000012345",
            normalized_phone_number="+919000012345",
            created_at=NOW,
        )
    )
    await db_session.flush()

    matches = await get_client_group_whatsapp_matches(
        group.id,
        broadcast_id=first.id,
        match_status="all",
        sort_by="name",
        sort_order="asc",
        page=1,
        page_size=100,
        current_user=viewer,
        session=db_session,
    )

    assert matches.selected_broadcast_id == first.id
    assert matches.counts.total_recipients == 1
    assert matches.total == 1
    assert set(matches.matches[0].broadcast_ids) == {
        first.id,
        second.id,
    }

    for unavailable_id in (unlinked.id, other_tenant.id):
        with pytest.raises(HTTPException) as unlinked_error:
            await get_client_group_whatsapp_matches(
                group.id,
                broadcast_id=unavailable_id,
                match_status="all",
                sort_by="name",
                sort_order="asc",
                page=1,
                page_size=100,
                current_user=viewer,
                session=db_session,
            )
        assert unlinked_error.value.status_code == 400


@pytest.mark.asyncio
async def test_match_api_exposes_imported_fields_and_evidence(
    db_session: AsyncSession,
) -> None:
    seeded = await _seed(db_session)
    group = seeded["group"]
    viewer = seeded["viewer"]
    recipients = (
        await db_session.scalars(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.normalized_phone_number == "+919876543210"
            )
        )
    ).all()
    for recipient in recipients:
        recipient.imported_fields = {
            "email": "irfan@example.com",
            "staff_code": "GC42",
            "zone_name": "North",
        }
    submission = PassportSubmissionModel(
        id=uuid.uuid4(),
        group_id=group.id,
        agency_id=seeded["agency_id"],
        client_name="Irfan Khan",
        client_email="IRFAN@example.com",
        client_phone="9000000000",
        image_s3_key="test/passport.jpg",
        status="submitted",
        confirmed_fields={
            "given_names": "Irfan",
            "surname": "Khan",
            "staff_code": "GC42",
        },
        created_at=NOW,
        updated_at=NOW,
    )
    db_session.add(submission)
    await db_session.flush()

    response = await get_client_group_whatsapp_matches(
        group.id,
        broadcast_id=None,
        match_status="all",
        sort_by="name",
        sort_order="asc",
        page=1,
        page_size=100,
        current_user=viewer,
        session=db_session,
    )

    assert response.counts.submitted_count == 1
    assert response.counts.matched_submission_count == 1
    row = response.matches[0]
    assert row.status == "submitted"
    assert row.confidence == "high"
    assert {evidence.kind for evidence in row.match_evidence} == {
        "email",
        "staff_code",
    }
    assert {item.fields["zone_name"] for item in row.recipient_fields} == {"North"}


@pytest.mark.asyncio
async def test_patch_without_link_field_preserves_links_and_cross_tenant_rejects(
    db_session: AsyncSession,
) -> None:
    seeded = await _seed(db_session)
    group = seeded["group"]
    creator = seeded["creator"]
    other_broadcast = seeded["other_broadcast"]
    request = UpdateClientGroupRequest(
        name="Renamed trip",
        whatsapp_broadcast_group_ids=None,
    )

    await update_client_group(
        group.id,
        request,
        current_user=creator,
        session=db_session,
    )
    link_count = await db_session.scalar(
        select(func.count())
        .select_from(ClientGroupWhatsAppBroadcastLinkModel)
        .where(ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id)
    )
    assert link_count == 2

    with pytest.raises(HTTPException) as cross_tenant:
        await _validate_broadcast_ids(
            db_session,
            agency_id=seeded["agency_id"],
            broadcast_ids=[other_broadcast.id],
        )
    assert cross_tenant.value.status_code == 400


@pytest.mark.asyncio
async def test_link_replacement_dedupes_and_is_idempotent(
    db_session: AsyncSession,
) -> None:
    seeded = await _seed(db_session)
    group = seeded["group"]
    creator = seeded["creator"]
    first, second, third = seeded["broadcasts"]
    same_request = ReplaceWhatsAppBroadcastLinksRequest(
        whatsapp_broadcast_group_ids=[
            first.id,
            first.id,
            second.id,
        ]
    )
    assert same_request.whatsapp_broadcast_group_ids == [
        first.id,
        second.id,
    ]
    before_rows = (
        await db_session.execute(
            select(
                ClientGroupWhatsAppBroadcastLinkModel.id,
                ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            )
            .where(ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id)
            .order_by(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
        )
    ).all()

    _, previous_ids, changed = await _replace_whatsapp_links(
        db_session,
        group_id=group.id,
        agency_id=seeded["agency_id"],
        created_by_user_id=creator.id,
        broadcast_ids=same_request.whatsapp_broadcast_group_ids,
    )
    after_same_rows = (
        await db_session.execute(
            select(
                ClientGroupWhatsAppBroadcastLinkModel.id,
                ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            )
            .where(ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id)
            .order_by(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
        )
    ).all()

    assert changed is False
    assert previous_ids == sorted([first.id, second.id], key=str)
    assert after_same_rows == before_rows

    different_request = ReplaceWhatsAppBroadcastLinksRequest(
        whatsapp_broadcast_group_ids=[
            second.id,
            third.id,
            third.id,
        ]
    )
    _, replaced_ids, changed = await _replace_whatsapp_links(
        db_session,
        group_id=group.id,
        agency_id=seeded["agency_id"],
        created_by_user_id=creator.id,
        broadcast_ids=different_request.whatsapp_broadcast_group_ids,
    )
    replacement_rows = (
        await db_session.scalars(
            select(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
            .where(ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id)
            .order_by(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
        )
    ).all()

    assert changed is True
    assert replaced_ids == sorted([first.id, second.id], key=str)
    assert replacement_rows == sorted([second.id, third.id])


def test_create_request_dedupes_and_limits_broadcast_ids() -> None:
    first = uuid.uuid4()
    request = CreateClientGroupRequest(
        name="Trip",
        destination="Thailand",
        travel_date=date(2026, 9, 1),
        return_date=date(2026, 9, 7),
        whatsapp_broadcast_group_ids=[first, first],
    )
    assert request.whatsapp_broadcast_group_ids == [first]

    with pytest.raises(ValidationError):
        CreateClientGroupRequest(
            name="Trip",
            destination="Thailand",
            travel_date=date(2026, 9, 1),
            return_date=date(2026, 9, 7),
            whatsapp_broadcast_group_ids=[uuid.uuid4() for _ in range(51)],
        )

    with pytest.raises(ValidationError):
        ReplaceWhatsAppBroadcastLinksRequest.model_validate({})


def test_public_token_response_model_has_no_whatsapp_metadata() -> None:
    assert "whatsapp_broadcasts" not in ClientGroupResponse.model_fields
    assert "whatsapp_broadcast_count" not in ClientGroupResponse.model_fields
    token_route = next(
        route
        for route in router.routes
        if route.path == "/token/{token}" and "GET" in (route.methods or set())
    )
    assert token_route.response_model is ClientGroupResponse
