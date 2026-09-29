"""Insert-only broadcast links preserve delivery and mobile identity state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.broadcast_link_changes import BroadcastLinkCommand, inspect_link_addition
from app.application.mcp.operations import MCPDatabaseContext, MCPOperationService
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
    MobileSyncChangeModel,
)
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSourceContactModel,
)
from app.presentation.mcp.broadcast_link_tools import _matching_fields, broadcast_link_definition
from app.presentation.mcp.invocation import MCPInputError
from tests.integration.test_mcp_office_changes import office_changes as office_changes
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.unit.infrastructure.test_whatsapp_source_group_sync import delivery, passenger


@pytest.fixture
async def link_changes(office_changes):
    base, agencies, group, _, _, _ = office_changes
    session = base[0]
    for grant in base[3]:
        grant.capabilities = ["mcp:read", "mcp:change"]
    broadcasts = [
        WhatsAppBroadcastGroupModel(
            id=uuid.uuid4(),
            agency_id=agencies[0].id,
            name="Synthetic broadcast",
            imported_field_keys=["name", "phone_number"],
        )
        for _ in range(2)
    ]
    session.add_all(broadcasts)
    await session.flush()
    old_link = ClientGroupWhatsAppBroadcastLinkModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        client_group_id=group.id,
        broadcast_group_id=broadcasts[1].id,
        matching_field_keys=["name"],
        sync_contacts_from_group=False,
    )
    session.add(old_link)
    people = [
        passenger(agencies[0].id, group.id, phone=phone, name=name)
        for phone, name in [
            ("9876543210", "First"),
            ("9876543210", "Shared"),
            ("9123456789", "Added"),
            ("invalid", "Invalid"),
        ]
    ]
    existing = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        broadcast_group_id=broadcasts[0].id,
        name="Retained manual name",
        phone_number="9876543210",
        normalized_phone_number="+919876543210",
        imported_fields={"retained": "exact"},
        is_source_managed=False,
    )
    session.add_all([*people, existing])
    await session.flush()
    return base, agencies, group, broadcasts, people, existing, old_link


async def inspect(f):
    session, settings, _, _, tokens = f[0]
    principal = await MCPAuthorizationService(session, settings).verify_access(
        tokens[0], "mcp:read"
    )
    return await inspect_link_addition(
        MCPDatabaseContext(session, principal, uuid.uuid4()),
        BroadcastLinkCommand(f[1][0].id, f[2].id, f[3][0].id, None),
        _matching_fields,
    )


async def payload_for(f):
    result = await inspect(f)
    return {
        "agency_id": result["agency_id"],
        "group_id": result["group_id"],
        "broadcast_id": result["broadcast_id"],
        "matching_field_keys": None,
        "expected_revision": result["source_revision"],
    }


async def execute(f, payload, *, key="add-broadcast-link-stable", connection=0):
    session, settings, _, _, tokens = f[0]
    return await MCPOperationService(session, settings, [broadcast_link_definition()]).execute(
        access_token=tokens[connection],
        operation_name="add_group_broadcast_link",
        idempotency_key=key,
        payload=payload,
    )


async def test_import_source_retains_shared_invalid_rows_and_manual_identity(link_changes):
    f = link_changes
    inspection = await inspect(f)
    assert inspection["recipient_additions"] == 1 and inspection["source_contact_additions"] == 4
    assert inspection["shared_source_phone_count"] == 1
    payload = await payload_for(f)
    result = await execute(f, payload)
    assert result["data"]["recipients_added"] == 1 and result["data"]["source_contacts_added"] == 4
    assert result["data"]["mobile_identities_added"] == 0
    assert (
        f[5].name == "Retained manual name"
        and f[5].imported_fields == {"retained": "exact"}
        and not f[5].is_source_managed
    )
    assert f[6].matching_field_keys == ["name"] and not f[6].sync_contacts_from_group
    contacts = list((await f[0][0].scalars(select(WhatsAppBroadcastSourceContactModel))).all())
    assert len(contacts) == 4 and sum(row.recipient_id == f[5].id for row in contacts) == 2
    assert next(row for row in contacts if row.name.startswith("Invalid")).issue == "invalid_phone"
    assert await execute(f, payload, connection=1) == result
    assert "9876543210" not in str(result)


async def test_non_import_group_adds_only_link(link_changes):
    f = link_changes
    f[2].import_only = False
    await f[0][0].flush()
    result = await execute(f, await payload_for(f))
    assert result["data"]["source_contacts_added"] == result["data"]["recipients_added"] == 0
    assert not result["data"]["sync_contacts_from_group"]


@pytest.mark.parametrize("state", ["queued", "processing", "delivery_unknown"])
async def test_private_ledger_is_never_cancelled_or_modified(link_changes, state):
    f = link_changes
    payload = await payload_for(f)
    row = delivery(f[1][0].id, f[2].id, f[3][0].id, state)
    f[0][0].add(row)
    await f[0][0].flush()
    with pytest.raises(MCPInputError, match="private delivery"):
        await execute(f, payload)
    assert row.status == state
    assert (
        await f[0][0].scalar(
            select(func.count()).select_from(ClientGroupWhatsAppBroadcastLinkModel)
        )
        == 1
    )
    assert (
        await f[0][0].scalar(select(func.count()).select_from(WhatsAppBroadcastSourceContactModel))
        == 0
    )


@pytest.mark.parametrize("change", ["removed", "merged", "suppressed"])
async def test_inactive_phone_collision_blocks_whole_proposal(link_changes, change):
    f = link_changes
    payload = await payload_for(f)
    if change == "removed":
        f[5].removed_at = datetime.now(UTC)
    elif change == "merged":
        f[5].merged_into_recipient_id = f[5].id
    else:
        # A retained suppression is tested by a pure model projection; do not
        # fabricate a foreign-key resolution row solely to mirror schema.
        from app.application.mcp.broadcast_link_plan import prepare_link_plan
        from app.application.mcp.broadcast_link_source import load_link_source

        principal = await MCPAuthorizationService(f[0][0], f[0][1]).verify_access(
            f[0][4][0], "mcp:change"
        )
        source = await load_link_source(
            MCPDatabaseContext(f[0][0], principal, uuid.uuid4()),
            agency_id=f[1][0].id,
            group_id=f[2].id,
            broadcast_id=f[3][0].id,
        )
        source.recipients[0].suppressed_by_roster_resolution_id = uuid.uuid4()
        from app.application.mcp.operations import MCPOperationError

        with pytest.raises(MCPOperationError, match="recipient_unavailable"):
            prepare_link_plan(source, None)
        f[0][0].expire(source.recipients[0])
        return
    await f[0][0].flush()
    with pytest.raises(MCPInputError, match="changed"):
        await execute(f, payload)
    from app.application.mcp.operations import MCPOperationError

    with pytest.raises(MCPOperationError, match="recipient_unavailable"):
        await inspect(f)


@pytest.mark.parametrize("change", ["phone", "name", "broadcast", "link"])
async def test_revision_fences_all_reviewed_sources(link_changes, change):
    f = link_changes
    payload = await payload_for(f)
    if change == "phone":
        f[4][2].staff_metadata = {"upload_phone": "9000000001"}
    elif change == "name":
        f[4][2].confirmed_fields = {"given_names": "Changed"}
    elif change == "broadcast":
        f[3][0].name = "Changed"
    else:
        f[6].matching_field_keys = ["phone_number"]
    await f[0][0].flush()
    with pytest.raises(MCPInputError, match="changed"):
        await execute(f, payload)
    assert (
        await f[0][0].scalar(select(func.count()).select_from(WhatsAppBroadcastSourceContactModel))
        == 0
    )


async def add_mobile(f):
    session = f[0][0]
    access = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=f[1][0].id,
        group_id=f[2].id,
        is_enabled=True,
        passenger_access_enabled=True,
    )
    person = f[4][2]
    person.image_s3_key = "passports/client-upload.jpg"
    person.client_phone = "+919123456789"
    person.staff_metadata = {}
    person.client_reviewed_at = datetime.now(UTC)
    session.add(access)
    await session.flush()
    return access, person


async def test_only_new_mobile_identity_uses_shared_journal_no_existing_session_effect(
    link_changes,
):
    f = link_changes
    access, person = await add_mobile(f)
    payload = await payload_for(f)
    result = await execute(f, payload)
    assert result["data"]["mobile_identities_added"] == 1
    identity = await f[0][0].scalar(select(MobilePassengerIdentityModel))
    assert (
        identity.passenger_submission_id == person.id
        and identity.claim_generation == 0
        and identity.status == "eligible"
    )
    assert await f[0][0].scalar(select(func.count()).select_from(MobileSyncChangeModel)) == 1
    assert await execute(f, payload, connection=1) == result


@pytest.mark.parametrize("change", ["phone", "revoke", "missing", "secondary"])
async def test_mobile_change_plan_blocks_before_any_link_contact_identity_or_journal_write(
    link_changes, change
):
    f = link_changes
    access, person = await add_mobile(f)
    identity = MobilePassengerIdentityModel(
        id=uuid.uuid4(),
        agency_id=f[1][0].id,
        group_id=f[2].id,
        gc_group_access_id=access.id,
        passenger_submission_id=person.id,
        normalized_phone_number="+919123456789",
        phone_lookup_hash="a" * 64,
        status="eligible",
        is_shared_number=False,
        requires_secondary_verification=False,
        claim_generation=7,
    )
    if change == "phone":
        identity.normalized_phone_number = "+919000000001"
    elif change == "revoke":
        identity.status = "revoked"
        identity.revoked_at = datetime.now(UTC)
    elif change == "missing":
        person.client_reviewed_at = None
    else:
        identity.secondary_factor_type = "employee_code"
        identity.secondary_factor_hash = "b" * 64
    f[0][0].add(identity)
    await f[0][0].flush()
    original = (
        identity.normalized_phone_number,
        identity.status,
        identity.claim_generation,
        identity.secondary_factor_hash,
    )
    from app.application.mcp.operations import MCPOperationError

    with pytest.raises(MCPOperationError, match="mobile_change_required"):
        await inspect(f)
    assert (
        identity.normalized_phone_number,
        identity.status,
        identity.claim_generation,
        identity.secondary_factor_hash,
    ) == original
    assert (
        await f[0][0].scalar(
            select(func.count()).select_from(ClientGroupWhatsAppBroadcastLinkModel)
        )
        == 1
    )
    assert await f[0][0].scalar(select(func.count()).select_from(MobileSyncChangeModel)) == 0


async def test_capacity_rejects_entire_addition_no_partial_import(link_changes, monkeypatch):
    f = link_changes
    payload = await payload_for(f)
    monkeypatch.setattr(
        "app.application.use_cases.whatsapp.recipient_capacity.MAX_WHATSAPP_RECIPIENTS", 1
    )
    with pytest.raises(MCPInputError, match="1500"):
        await execute(f, payload)
    assert (
        await f[0][0].scalar(select(func.count()).select_from(WhatsAppBroadcastSourceContactModel))
        == 0
    )


@pytest.mark.parametrize("change", ["group_agency", "broadcast_agency", "archived", "deleted"])
async def test_current_scope_blocks_mutation(link_changes, change):
    f = link_changes
    payload = await payload_for(f)
    if change == "group_agency":
        payload["agency_id"] = str(f[1][1].id)
    elif change == "broadcast_agency":
        f[3][0].agency_id = f[1][1].id
    elif change == "archived":
        f[3][0].archived_at = datetime.now(UTC)
    else:
        f[2].deleted_at = datetime.now(UTC)
    await f[0][0].flush()
    with pytest.raises(MCPInputError):
        await execute(f, payload)


async def test_actual_sdk_inspect_mutation_and_retry_are_audited(link_changes, monkeypatch):
    from contextlib import asynccontextmanager

    from fastapi import FastAPI
    from mcp.server import MCPServer
    from mcp.server.auth.provider import AccessToken

    from app.presentation.mcp.broadcast_link_tools import register_broadcast_link_tools

    f = link_changes
    session, settings, actor, grants, tokens = f[0]
    await session.commit()

    @asynccontextmanager
    async def factory():
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise

    app, server = FastAPI(), MCPServer("Link fixture")
    app.state.mcp_session_factory = factory
    app.state.mcp_operations = {}
    register_broadcast_link_tools(server, app, settings)
    monkeypatch.setattr(
        "app.presentation.mcp.invocation.get_access_token",
        lambda: AccessToken(
            token=tokens[0],
            client_id="global-connects-desktop",
            scopes=["mcp:read", "mcp:change"],
            subject=str(actor.id),
            resource=settings.mcp.resource,
            claims={"grant_id": str(grants[0].id)},
        ),
    )
    selection = {
        "agency_id": str(f[1][0].id),
        "group_id": str(f[2].id),
        "broadcast_id": str(f[3][0].id),
    }
    read = (
        await server.call_tool("inspect_group_broadcast_addition", {"selection": selection})
    ).structured_content
    assert read["recipient_additions"] == 1 and read["audit_id"]
    args = {
        "association": {**selection, "expected_revision": read["source_revision"]},
        "idempotency_key": "sdk-broadcast-link-addition",
    }
    first = (await server.call_tool("add_group_broadcast_link", args)).structured_content
    second = (await server.call_tool("add_group_broadcast_link", args)).structured_content
    assert "receipt" in first, first
    assert first["receipt"] == second["receipt"] and first["audit_id"] != second["audit_id"]
    assert not session.in_transaction()


async def test_receipt_cannot_observe_removed_link_or_recipient(link_changes):
    f = link_changes
    payload = await payload_for(f)
    await execute(f, payload)
    f[5].removed_at = datetime.now(UTC)
    await f[0][0].flush()
    with pytest.raises(MCPInputError, match="unavailable"):
        await execute(f, payload)


async def test_existing_mobile_binding_remains_exact_while_only_new_identity_is_added(
    link_changes, monkeypatch
):
    from unittest.mock import AsyncMock

    f = link_changes
    await add_mobile(f)
    await execute(f, await payload_for(f))
    session = f[0][0]
    identity = await session.scalar(select(MobilePassengerIdentityModel))
    before = (
        identity.id,
        identity.status,
        identity.claim_generation,
        identity.phone_lookup_hash,
        identity.updated_at,
    )
    broadcast = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(),
        agency_id=f[1][0].id,
        name="Another destination",
        imported_field_keys=["name", "phone_number"],
    )
    person = passenger(f[1][0].id, f[2].id, phone="9000000001", name="New public")
    person.image_s3_key = "passports/new-public.jpg"
    person.client_phone = "+919000000001"
    person.staff_metadata = {}
    session.add_all([broadcast, person])
    await session.flush()
    f[3][0] = broadcast
    revoke = AsyncMock()
    monkeypatch.setattr(
        "app.application.mobile.passenger_identity_reconciliation._revoke_passenger_identity_sessions",
        revoke,
    )
    result = await execute(f, await payload_for(f), key="another-link-with-new-mobile")
    assert result["data"]["mobile_identities_added"] == 1
    assert (
        identity.id,
        identity.status,
        identity.claim_generation,
        identity.phone_lookup_hash,
        identity.updated_at,
    ) == before
    revoke.assert_not_awaited()


async def test_retained_source_contact_conflict_is_never_overwritten(link_changes):
    from app.application.mcp.operations import MCPOperationError

    f = link_changes
    row = WhatsAppBroadcastSourceContactModel(
        id=uuid.uuid4(),
        agency_id=f[1][0].id,
        broadcast_group_id=f[3][0].id,
        source_group_id=f[2].id,
        source_submission_id=f[4][0].id,
        recipient_id=f[5].id,
        name="Retained changed name",
        raw_phone_number="9876543210",
        normalized_phone_number="+919876543210",
        imported_fields={"retained": "exact"},
    )
    f[0][0].add(row)
    await f[0][0].flush()
    with pytest.raises(MCPOperationError, match="retained_contact_conflict"):
        await inspect(f)
    assert row.name == "Retained changed name" and row.imported_fields == {"retained": "exact"}


async def test_retained_phone_override_blocks_without_deletion(link_changes):
    from app.application.mcp.operations import MCPOperationError
    from app.infrastructure.database.models import WhatsAppTravellerPhoneOverrideModel

    f = link_changes
    row = WhatsAppTravellerPhoneOverrideModel(
        id=uuid.uuid4(),
        agency_id=f[1][0].id,
        group_id=f[2].id,
        broadcast_group_id=f[3][0].id,
        passenger_id=f[4][0].id,
        recipient_id=f[5].id,
        source_phone_fingerprint="a" * 64,
    )
    f[0][0].add(row)
    await f[0][0].flush()
    with pytest.raises(MCPOperationError, match="retained_override"):
        await inspect(f)
    assert await f[0][0].get(WhatsAppTravellerPhoneOverrideModel, row.id) is row


async def test_proposed_link_cannot_suppress_a_current_recipient_for_replacement(link_changes):
    from app.application.mcp.operations import MCPOperationError
    from app.infrastructure.database.models import PassportRosterResolutionModel

    f = link_changes
    resolution = PassportRosterResolutionModel(
        id=uuid.uuid4(),
        agency_id=f[1][0].id,
        client_group_id=f[2].id,
        submission_id=f[4][2].id,
        broadcast_recipient_id=f[5].id,
        replaced_recipient_normalized_phone=f[5].normalized_phone_number,
        original_recipient_phone=f[5].phone_number,
        resolution_type="replacement",
        status="active",
    )
    f[0][0].add(resolution)
    await f[0][0].flush()
    with pytest.raises(MCPOperationError, match="replacement_conflict"):
        await inspect(f)
    assert f[5].removed_at is None and f[5].suppressed_by_roster_resolution_id is None


async def test_actual_5001_source_rows_fail_closed_before_creating_link(link_changes):
    from app.application.mcp.operations import MCPOperationError

    f = link_changes
    f[0][0].add_all(passenger(f[1][0].id, f[2].id, phone="", name="Bound") for _ in range(4997))
    await f[0][0].flush()
    with pytest.raises(MCPOperationError, match="scope_too_large"):
        await inspect(f)
    assert (
        await f[0][0].scalar(
            select(func.count()).select_from(ClientGroupWhatsAppBroadcastLinkModel)
        )
        == 1
    )


async def test_existing_exact_link_returns_without_sync_or_implicit_configuration_change(
    link_changes,
):
    f = link_changes
    await execute(f, await payload_for(f))
    result = await execute(f, await payload_for(f), key="deliberate-new-existing-link")
    assert result["data"]["outcome"] == "existing" and result["data"]["recipients_added"] == 0
    payload = await payload_for(f)
    payload["matching_field_keys"] = ["name"]
    with pytest.raises(MCPInputError, match="already exists"):
        await execute(f, payload, key="cannot-replace-link-fields")
