"""Invited accounts and GC settings retain authority, history and safe retries."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request, Response
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.domain.mcp_section_permissions import SUPPORTED_WRITE_SECTIONS
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    ClientOrganizationModel,
    GCGroupAccessModel,
    GCItineraryVersionModel,
    MobileSyncChangeModel,
)
from app.infrastructure.database.identity_security_models import (
    IdentityActionTokenModel,
    IdentityNotificationOutboxModel,
)
from app.infrastructure.database.mcp_models import MCPControlModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import admin_accounts, gc_app
from app.presentation.mcp.business_admin_tools import (
    BUSINESS_TOOL_MODELS,
    business_definition,
    register_business_admin_tools,
)
from app.presentation.mcp.invocation import MCPInputError
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture


@pytest.fixture
async def business_admin(operations_fixture):
    session, settings, actor, grants, tokens = operations_fixture
    control = await session.get(MCPControlModel, 1)
    control.write_enabled = True
    control.allowed_write_sections = sorted(SUPPORTED_WRITE_SECTIONS)
    control.allowed_write_tools = sorted(BUSINESS_TOOL_MODELS)
    for grant in grants:
        grant.write_enabled = True
        grant.allowed_write_sections = sorted(SUPPORTED_WRITE_SECTIONS)
    agencies = [
        AgencyModel(id=uuid.uuid4(), name="Business agency", email=f"business-{i}@example.test")
        for i in range(2)
    ]
    session.add_all(agencies)
    await session.flush()
    actor.agency_id = agencies[0].id
    actor.email = "business-admin@example.com"
    organization = ClientOrganizationModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        name="Selected company",
        normalized_name="selected company",
    )
    group = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        name="Published trip",
        token="SECRET_UPLOAD",
        import_only=True,
        travel_date=date(2030, 1, 1),
        return_date=date(2030, 1, 5),
    )
    session.add_all([organization, group])
    await session.flush()
    access = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        group_id=group.id,
        client_organization_id=organization.id,
        is_enabled=True,
        passenger_access_enabled=False,
        client_manager_access_enabled=True,
        coordinator_access_enabled=True,
    )
    session.add(access)
    await session.flush()
    service = MCPOperationService(
        session, settings, [business_definition(name) for name in BUSINESS_TOOL_MODELS]
    )
    return operations_fixture, agencies, organization, group, access, service


def account_input(fixture, *, kind="coordinator"):
    return {
        "agency_id": str(fixture[1][0].id),
        "account_type": kind,
        "full_name": "  Invited   Person ",
        "email": f"{kind}-new@example.com",
        "credential_delivery": "dashboard_activation",
    }


def client_manager_input(fixture):
    return {
        "agency_id": str(fixture[1][0].id),
        "organization_id": str(fixture[2].id),
        "group_ids": [str(fixture[3].id)],
        "full_name": "Client Manager",
        "email": "client-new@example.com",
        "phone_number": "+919876543210",
        "credential_delivery": "dashboard_activation",
    }


async def execute(fixture, name, payload, *, key="business-admin-request-001", connection=0):
    return await fixture[5].execute(
        access_token=fixture[0][4][connection],
        operation_name=name,
        idempotency_key=key,
        payload=payload,
    )


@pytest.mark.parametrize("kind", ["coordinator", "staff", "manager"])
async def test_invited_account_atomic_retry_and_real_dashboard_activation_handoff(
    business_admin, kind, monkeypatch
):
    fixture = business_admin
    session, _, actor, _, _ = fixture[0]
    raw_tokens = []
    original = IdentitySecurityRepository.issue_action_token

    async def capture(self, **kwargs):
        value = await original(self, **kwargs)
        raw_tokens.append(value[1])
        return value

    monkeypatch.setattr(IdentitySecurityRepository, "issue_action_token", capture)
    payload = account_input(fixture, kind=kind)
    receipt = await execute(fixture, "create_workforce_account", payload)
    assert await execute(fixture, "create_workforce_account", payload, connection=1) == receipt
    account = await session.get(UserModel, uuid.UUID(receipt["data"]["account_id"]))
    state = await session.get(UserSecurityStateModel, account.id)
    assert account.role == f"agency_{kind}" and account.full_name == "Invited Person"
    assert state.credential_state == "invited" and state.mfa_required is True
    assert (
        receipt["data"]["notifications_sent"] == 0
        and receipt["data"]["activation_required"] is True
    )
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 1
    assert await session.scalar(select(func.count()).select_from(IdentityActionTokenModel)) == 1
    assert (
        await session.scalar(select(func.count()).select_from(IdentityNotificationOutboxModel)) == 0
    )
    audits = list((await session.scalars(select(AuditLogModel))).all())
    safe = json.dumps(receipt) + json.dumps([a.metadata_json for a in audits])
    assert all(token not in safe for token in raw_tokens)
    assert account.hashed_password not in safe and "activation_token" not in safe

    # The exact existing dashboard handler can issue a usable replacement link
    # for all three roles. This is the advertised separate credential handoff.
    dashboard_actor = await UserRepository(session).get_by_id(actor.id)
    response = await admin_accounts.reset_managed_account_password(
        account.id,
        admin_accounts.ResetManagedAccountPasswordRequest(),
        Request({"type": "http", "headers": [], "client": None}),
        Response(),
        current_user=dashboard_actor,
        session=session,
    )
    assert response.activation_token and response.activation_token != raw_tokens[0]
    tokens = list((await session.scalars(select(IdentityActionTokenModel))).all())
    assert len(tokens) == 2 and sum(t.invalidated_at is None for t in tokens) == 1
    assert await execute(fixture, "create_workforce_account", payload) == receipt


@pytest.mark.parametrize(
    "change",
    ["foreign_agency", "stale_mfa", "non_superadmin", "inactive_agency", "duplicate_identity"],
)
async def test_creation_current_authority_and_identity_fail_closed(business_admin, change):
    fixture = business_admin
    payload = account_input(fixture)
    if change == "foreign_agency":
        payload["agency_id"] = str(fixture[1][1].id)
    elif change == "stale_mfa":
        fixture[0][3][0].mfa_at = datetime.now(UTC) - timedelta(minutes=11)
    elif change == "non_superadmin":
        fixture[0][2].role = "agency_manager"
    elif change == "inactive_agency":
        fixture[1][0].is_active = False
    else:
        payload["email"] = fixture[0][2].email
    await fixture[0][0].flush()
    with pytest.raises((MCPInputError, MCPAuthError)):
        await execute(fixture, "create_workforce_account", payload)
    assert await fixture[0][0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    assert (
        await fixture[0][0].scalar(select(func.count()).select_from(IdentityActionTokenModel)) == 0
    )


async def test_creation_audit_failure_rolls_back_account_activation_and_receipt(
    business_admin, monkeypatch
):
    fixture = business_admin
    monkeypatch.setattr(
        AuditLogRepository, "record", AsyncMock(side_effect=RuntimeError("qualified audit failure"))
    )
    with pytest.raises(RuntimeError, match="qualified audit failure"):
        await execute(fixture, "create_workforce_account", account_input(fixture))
    session = fixture[0][0]
    assert await session.scalar(select(func.count()).select_from(UserModel)) == 1
    assert await session.scalar(select(func.count()).select_from(IdentityActionTokenModel)) == 0
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_client_manager_retains_private_assignments_and_uses_dashboard_handoff(
    business_admin,
):
    fixture = business_admin
    payload = client_manager_input(fixture)
    receipt = await execute(fixture, "create_gc_client_manager_account", payload)
    assert (
        await execute(fixture, "create_gc_client_manager_account", payload, connection=1) == receipt
    )
    session = fixture[0][0]
    profile = await session.get(ClientManagerProfileModel, uuid.UUID(receipt["data"]["profile_id"]))
    assignments = list((await session.scalars(select(ClientManagerGroupAssignmentModel))).all())
    assert (
        profile.status == "invited"
        and profile.invitation_token_hash
        and len(profile.invitation_token_hash) == 64
    )
    assert len(assignments) == 1 and assignments[0].gc_group_access_id == fixture[4].id
    assert (
        assignments[0].can_view_passenger_names is False
        and assignments[0].personal_document_access_enabled is False
    )
    assert profile.invitation_token_hash not in json.dumps(
        receipt
    ) and "activation_token" not in json.dumps(receipt)
    assert (
        await session.scalar(select(func.count()).select_from(IdentityNotificationOutboxModel)) == 0
    )
    dashboard_actor = await UserRepository(session).get_by_id(fixture[0][2].id)
    invitation = await gc_app.reset_client_manager_password(
        profile.id,
        gc_app.ClientManagerPasswordResetRequest(),
        Request({"type": "http", "headers": [], "client": None}),
        Response(),
        agency_id=profile.agency_id,
        current_user=dashboard_actor,
        session=session,
    )
    assert (
        invitation.activation_token
        and gc_app.hash_mobile_lookup(invitation.activation_token, purpose="manager-invitation")
        == profile.invitation_token_hash
    )
    assert invitation.activation_token not in json.dumps(receipt)
    profile.status, profile.suspended_at = "suspended", datetime.now(UTC)
    await session.flush()
    with pytest.raises(MCPOperationError, match="account_creation_receipt_unavailable"):
        await execute(fixture, "create_gc_client_manager_account", payload)


@pytest.mark.parametrize(
    "change", ["foreign_organization", "foreign_group", "invalid_phone", "duplicate_phone"]
)
async def test_client_manager_canonical_identity_organization_and_group_checks(
    business_admin, change
):
    fixture = business_admin
    payload = client_manager_input(fixture)
    if change == "foreign_organization":
        other = ClientOrganizationModel(
            id=uuid.uuid4(), agency_id=fixture[1][1].id, name="Foreign", normalized_name="foreign"
        )
        fixture[0][0].add(other)
        await fixture[0][0].flush()
        payload["organization_id"] = str(other.id)
    elif change == "foreign_group":
        payload["group_ids"] = [str(uuid.uuid4())]
    elif change == "invalid_phone":
        payload["phone_number"] = "not-a-mobile"
    else:
        await execute(fixture, "create_gc_client_manager_account", payload)
        payload["email"] = "other-client@example.com"
    with pytest.raises(MCPInputError):
        await execute(
            fixture,
            "create_gc_client_manager_account",
            payload,
            key="different-account-request-001",
        )
    assert await fixture[0][0].scalar(
        select(func.count()).select_from(ClientManagerProfileModel)
    ) == (1 if change == "duplicate_phone" else 0)


async def test_gc_settings_revisions_add_disable_and_photo_changes_retain_history(business_admin):
    fixture = business_admin
    session, access = fixture[0][0], fixture[4]
    settings = {
        "agency_id": str(fixture[3].agency_id),
        "group_id": str(fixture[3].id),
        "client_organization_id": str(fixture[2].id),
        "enabled": False,
        "passenger_access_enabled": False,
        "client_manager_access_enabled": False,
        "coordinator_access_enabled": False,
        "expected_revision": access.revision,
    }
    receipt = await execute(fixture, "configure_gc_group_access", settings)
    await session.refresh(access)
    assert access.is_enabled is False and access.revoked_at and access.revision == 2
    assert receipt["data"]["history_retained"] is True
    before = await session.scalar(select(func.count()).select_from(MobileSyncChangeModel))
    assert before > 0
    assert await execute(fixture, "configure_gc_group_access", settings, connection=1) == receipt
    with pytest.raises(MCPInputError, match="current application rules"):
        await execute(
            fixture,
            "configure_gc_group_access",
            {**settings, "enabled": True},
            key="stale-revision-request-001",
        )
    assert await session.scalar(select(func.count()).select_from(MobileSyncChangeModel)) == before
    photos = {
        "agency_id": str(access.agency_id),
        "group_id": str(access.group_id),
        "enabled": True,
        "expected_revision": 2,
    }
    with pytest.raises(MCPInputError):
        await execute(fixture, "configure_gc_my_photos", photos)
    await execute(
        fixture,
        "configure_gc_group_access",
        {**settings, "enabled": True, "passenger_access_enabled": True, "expected_revision": 2},
        key="explicit-enable-passenger-001",
    )
    photos["expected_revision"] = 3
    photo_receipt = await execute(fixture, "configure_gc_my_photos", photos)
    await session.refresh(access)
    assert (
        photo_receipt["data"]["configuration"]["my_photos_enabled"] is True and access.revision == 4
    )
    assert await execute(fixture, "configure_gc_my_photos", photos) == photo_receipt


async def test_new_gc_group_uses_explicit_roles_and_existing_organization(business_admin):
    fixture = business_admin
    group = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=fixture[1][0].id,
        name="New published group",
        token="OTHER_UPLOAD",
        import_only=True,
    )
    fixture[0][0].add(group)
    await fixture[0][0].flush()
    body = {
        "agency_id": str(group.agency_id),
        "group_id": str(group.id),
        "client_organization_id": str(fixture[2].id),
        "enabled": False,
        "passenger_access_enabled": False,
        "client_manager_access_enabled": True,
        "coordinator_access_enabled": False,
    }
    receipt = await execute(fixture, "configure_gc_group_access", body)
    assert receipt["data"]["configuration"]["revision"] == 1
    assert receipt["data"]["configuration"]["client_manager_access_enabled"] is True
    assert await fixture[0][0].scalar(select(func.count()).select_from(GCGroupAccessModel)) == 2


async def test_publish_retains_prior_versions_and_fences_stale_access_revision(business_admin):
    fixture = business_admin
    session, access, actor = fixture[0][0], fixture[4], fixture[0][2]
    now = datetime.now(UTC)
    versions = [
        GCItineraryVersionModel(
            id=uuid.uuid4(),
            agency_id=access.agency_id,
            group_id=access.group_id,
            gc_group_access_id=access.id,
            version=i + 1,
            title="Retained version",
            status="published" if i == 0 else "draft",
            content_checksum="a" * 64,
            published_at=now if i == 0 else None,
            created_by_user_id=actor.id,
        )
        for i in range(2)
    ]
    session.add_all(versions)
    await session.flush()
    body = {
        "agency_id": str(access.agency_id),
        "group_id": str(access.group_id),
        "version_id": str(versions[1].id),
        "expected_access_revision": access.revision,
    }
    with pytest.raises(MCPInputError):
        await execute(
            fixture,
            "publish_gc_itinerary",
            {**body, "expected_access_revision": access.revision + 1},
        )
    receipt = await execute(fixture, "publish_gc_itinerary", body)
    await session.refresh(versions[0])
    await session.refresh(versions[1])
    await session.refresh(access)
    assert [v.status for v in versions] == ["retired", "published"]
    assert access.revision == 2 and access.itinerary_version == 1
    assert "days" not in receipt["data"]["configuration"]
    assert await execute(fixture, "publish_gc_itinerary", body) == receipt
    assert await session.scalar(select(func.count()).select_from(GCItineraryVersionModel)) == 2


async def test_sdk_creation_commits_safe_receipt_and_audits_without_credentials(
    business_admin, monkeypatch
):
    fixture = business_admin
    session, settings, actor, grants, tokens = fixture[0]
    await session.commit()
    app, server = FastAPI(), MCPServer("Business administration fixture")

    @asynccontextmanager
    async def sessions():
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    register_business_admin_tools(server, app, settings)
    monkeypatch.setattr(
        "app.presentation.mcp.invocation.get_access_token",
        lambda: AccessToken(
            token=tokens[0],
            client_id=grants[0].client_id,
            scopes=["mcp:change"],
            subject=str(actor.id),
        ),
    )
    result = await server.call_tool(
        "create_workforce_account",
        {"account": account_input(fixture), "idempotency_key": "native-account-request-001"},
    )
    assert not result.is_error
    serialized = json.dumps(result.model_dump(mode="json"))
    assert (
        "invited" in serialized
        and "activation_token" not in serialized
        and "hashed_password" not in serialized
    )
    audit = await session.scalar(
        select(AuditLogModel).where(AuditLogModel.action == "mcp.tool.create_workforce_account")
    )
    assert audit.result == "success" and audit.metadata_json["capability"] == "mcp:change"
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert set(tools) == set(BUSINESS_TOOL_MODELS)
    assert (
        tools["create_workforce_account"].input_schema["$defs"]["MCPWorkforceAccount"][
            "additionalProperties"
        ]
        is False
    )


async def test_workforce_permission_is_role_specific_and_rechecked_for_receipt(business_admin):
    fixture = business_admin
    session = fixture[0][0]
    control = await session.get(MCPControlModel, 1)
    control.allowed_write_sections = ["coordinators"]
    for grant in fixture[0][3]:
        grant.allowed_write_sections = ["coordinators"]
    await session.flush()
    receipt = await execute(fixture, "create_workforce_account", account_input(fixture))
    assert receipt["data"]["account_type"] == "coordinator"
    with pytest.raises(MCPAuthError, match="write_section_denied"):
        await execute(
            fixture,
            "create_workforce_account",
            account_input(fixture, kind="manager"),
            key="denied-manager-request-001",
        )
    control.allowed_write_sections = []
    await session.flush()
    with pytest.raises(MCPAuthError):
        await execute(fixture, "create_workforce_account", account_input(fixture))
    with pytest.raises(MCPAuthError):
        await fixture[5].inspect(
            access_token=fixture[0][4][0], operation_id=uuid.UUID(receipt["operation_id"])
        )
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 1
