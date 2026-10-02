"""Deleting a listed authorization revokes access while preserving provenance."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError, pkce_challenge, utc
from app.infrastructure.database.mcp_artifact_models import MCPArtifactAccessModel, MCPArtifactModel
from app.infrastructure.database.mcp_models import (
    MCPAuthorizationCodeModel,
    MCPGrantModel,
    MCPTokenModel,
)
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import AgencyModel, AuditLogModel, ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from tests.dashboard_session_fixtures import issue_dashboard_access
from tests.integration.test_mcp_authorization import CLIENT, REDIRECT, RESOURCE, VERIFIER, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture
from tests.integration.test_mcp_device_access import exchange, set_access


async def remove(fixture, identifier):
    return await fixture[0].delete(
        f"/api/v1/admin/mcp/connections/{identifier}",
        headers={"Authorization": f"Bearer {fixture[5]}"},
    )


@pytest.mark.parametrize("state", ["active", "disabled", "revoked", "expired"])
async def test_delete_hides_connection_revokes_credentials_and_is_idempotent(mcp_fixture, state):
    client, session, settings, user, _, dashboard = mcp_fixture
    _, tokens = await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    now, unused_code = datetime.now(UTC), "gcmcp_code_" + "unused-delete-proof-" * 3
    code_row = MCPAuthorizationCodeModel(
        code_hash=MCPAuthorizationService(session, settings).digest(unused_code),
        grant_id=grant.id,
        redirect_uri=REDIRECT,
        code_challenge=pkce_challenge(VERIFIER),
        expires_at=now + timedelta(minutes=1),
    )
    session.add(code_row)
    if state == "disabled":
        grant.enabled = False
    elif state == "revoked":
        grant.revoked_at, grant.revocation_reason = (
            now - timedelta(minutes=1),
            "administrator_revoked",
        )
    elif state == "expired":
        grant.created_at, grant.expires_at = now - timedelta(days=8), now - timedelta(days=1)
    await session.commit()
    previous = (grant.enabled, list(grant.capabilities), grant.revoked_at)
    counts = [
        await session.scalar(select(func.count()).select_from(model))
        for model in (MCPGrantModel, MCPTokenModel, MCPAuthorizationCodeModel)
    ]
    deleted = await remove(mcp_fixture, grant.id)
    assert deleted.status_code == 200 and deleted.json() == {"deleted": True}
    await session.refresh(grant)
    assert grant.revocation_reason == "administrator_removed" and grant.revoked_at is not None
    assert (grant.enabled, grant.capabilities) == previous[:2]
    if previous[2] is not None:
        assert utc(grant.revoked_at) == utc(previous[2])
    first_revoked_at = grant.revoked_at
    listing = await client.get(
        "/api/v1/admin/mcp/connections", headers={"Authorization": f"Bearer {dashboard}"}
    )
    assert listing.status_code == 200 and listing.json()["items"] == []
    with pytest.raises(MCPAuthError) as denied:
        await MCPAuthorizationService(session, settings).verify_access(tokens["access_token"])
    assert denied.value.error == "invalid_grant"
    refresh = await client.post(
        "/oauth/mcp/token",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT,
            "resource": RESOURCE,
            "refresh_token": tokens["refresh_token"],
        },
    )
    assert refresh.status_code == 400 and refresh.json()["error"] == "invalid_grant"
    assert (await exchange(client, unused_code)).status_code == 400
    assert (await set_access(mcp_fixture, grant.id, True)).status_code == 409
    refresh_row = await session.get(
        MCPTokenModel, MCPAuthorizationService(session, settings).digest(tokens["refresh_token"])
    )
    await session.refresh(code_row)
    assert refresh_row.consumed_at is None and code_row.consumed_at is None
    repeated = await remove(mcp_fixture, grant.id)
    assert repeated.status_code == 200 and repeated.json() == {"deleted": True}
    await session.refresh(grant)
    assert grant.revoked_at == first_revoked_at
    assert [
        await session.scalar(select(func.count()).select_from(model))
        for model in (MCPGrantModel, MCPTokenModel, MCPAuthorizationCodeModel)
    ] == counts
    audits = list(
        (
            await session.scalars(
                select(AuditLogModel).where(AuditLogModel.action == "mcp.connection_removed")
            )
        ).all()
    )
    assert (
        len(audits) == 1 and audits[0].user_id == user.id and audits[0].entity_id == str(grant.id)
    )
    assert audits[0].metadata_json == {
        "previous_revocation_reason": "administrator_revoked" if state == "revoked" else None,
        "revoked_now": state != "revoked",
    }
    assert (await AuditLogRepository(session).verify_chain(None)).valid


async def test_delete_preserves_linked_operation_artifact_access_and_normal_revoke(mcp_fixture):
    client, session, _, user, _, dashboard = mcp_fixture
    await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    now = datetime.now(UTC)
    agency = AgencyModel(
        id=uuid.uuid4(), name="Retained deletion fixture", email="delete-agency@example.test"
    )
    session.add(agency)
    await session.flush()
    group = ClientGroupModel(
        id=uuid.uuid4(), agency_id=agency.id, name="Retained group", token=uuid.uuid4().hex
    )
    operation = MCPOperationModel(
        id=uuid.uuid4(),
        user_id=user.id,
        initial_grant_id=grant.id,
        operation_name="retained-delete-proof",
        capability="mcp:read",
        idempotency_hash="a" * 64,
        payload_hash="b" * 64,
        initial_result={"retained": True},
        workflow_id=uuid.uuid4(),
        status="succeeded",
        progress=1,
        stage="completed",
        revision=1,
        created_entities=[],
        created_at=now,
        updated_at=now,
    )
    session.add_all([group, operation])
    await session.flush()
    artifact = MCPArtifactModel(
        id=uuid.uuid4(),
        handle_hash="c" * 64,
        user_id=user.id,
        grant_id=grant.id,
        agency_id=agency.id,
        group_id=group.id,
        direction="export",
        purpose="retained-delete-proof",
        storage_key="retained-delete-proof",
        filename="retained.pdf",
        media_type="application/pdf",
        byte_size=10,
        sha256="d" * 64,
        created_at=now,
        expires_at=now + timedelta(days=1),
        ingestion_operation_id=operation.id,
    )
    session.add(artifact)
    await session.flush()
    access = MCPArtifactAccessModel(
        artifact_id=artifact.id, grant_id=grant.id, handle_hash="e" * 64, handle_version=1
    )
    session.add(access)
    await session.commit()
    headers = {"Authorization": f"Bearer {dashboard}"}
    revoked = await client.post(f"/api/v1/admin/mcp/connections/{grant.id}/revoke", headers=headers)
    assert revoked.status_code == 200
    await session.refresh(grant)
    revoked_at = grant.revoked_at
    assert grant.revocation_reason == "administrator_revoked"
    assert (
        len((await client.get("/api/v1/admin/mcp/connections", headers=headers)).json()["items"])
        == 1
    )
    assert (await remove(mcp_fixture, grant.id)).status_code == 200
    for row in (grant, operation, artifact, access):
        await session.refresh(row)
    assert grant.revoked_at == revoked_at and grant.revocation_reason == "administrator_removed"
    assert operation.initial_grant_id == grant.id and operation.initial_result == {"retained": True}
    assert (
        artifact.grant_id == access.grant_id == grant.id
        and artifact.ingestion_operation_id == operation.id
    )
    assert artifact.storage_key == "retained-delete-proof"
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 1
    assert await session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 1
    assert await session.scalar(select(func.count()).select_from(MCPArtifactAccessModel)) == 1


@pytest.mark.parametrize(
    "role",
    ["agency_admin", "agency_manager", "agency_staff", "agency_coordinator", "client_manager"],
)
async def test_delete_is_superadmin_only(mcp_fixture, role):
    _, session, _, user, _, _ = mcp_fixture
    await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    user.role = role
    await session.commit()
    denied = await remove(mcp_fixture, grant.id)
    assert denied.status_code in {401, 403}
    await session.refresh(grant)
    assert grant.revoked_at is None and grant.revocation_reason is None


@pytest.mark.parametrize("guard", ["anonymous", "cookie_csrf", "stale_mfa"])
async def test_delete_requires_session_csrf_recent_mfa_and_audits_denials(mcp_fixture, guard):
    client, session, _, user, _, dashboard = mcp_fixture
    await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    headers = {}
    if guard == "cookie_csrf":
        client.cookies.set("access_token", dashboard)
        headers["Origin"] = "https://attacker.example"
    elif guard == "stale_mfa":
        stale, _ = await issue_dashboard_access(
            session,
            user.id,
            "super_admin",
            session_version=1,
            authentication_methods=("pwd", "totp"),
            mfa_authenticated_at=datetime.now(UTC) - timedelta(minutes=11),
        )
        headers["Authorization"] = f"Bearer {stale}"
    denied = await client.delete(f"/api/v1/admin/mcp/connections/{grant.id}", headers=headers)
    assert denied.status_code == (401 if guard == "anonymous" else 403)
    await session.refresh(grant)
    assert grant.revoked_at is None and grant.revocation_reason is None
    async with client._transport.app.state.mcp_management_audit_session_factory() as audit_session:
        audits = list((await audit_session.scalars(select(AuditLogModel))).all())
        assert len(audits) == 1 and audits[0].action == "mcp.management_rejected"
        assert (
            audits[0].entity_id == str(grant.id)
            and audits[0].metadata_json["operation"] == "delete_connection"
        )
        assert (await AuditLogRepository(audit_session).verify_chain(None)).valid


async def test_delete_unknown_id_returns_404_without_success_audit(mcp_fixture):
    _, session, *_ = mcp_fixture
    response = await remove(mcp_fixture, uuid.uuid4())
    assert response.status_code == 404 and response.json()["detail"] == "Connection not found"
    assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 0
    assert (
        await session.scalar(
            select(func.count())
            .select_from(AuditLogModel)
            .where(AuditLogModel.action == "mcp.connection_removed")
        )
        == 0
    )


async def test_delete_rolls_back_when_chained_success_audit_fails(mcp_fixture, monkeypatch):
    client, session, _, _, _, dashboard = mcp_fixture
    await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    await session.commit()
    original_record = AuditLogRepository.record

    async def fail_success_audit(self, **arguments):
        if arguments["action"] == "mcp.connection_removed":
            raise RuntimeError("simulated deletion audit failure")
        return await original_record(self, **arguments)

    async def transactional_session():
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

    monkeypatch.setattr(AuditLogRepository, "record", fail_success_audit)
    client._transport.app.dependency_overrides[get_db_session] = transactional_session
    with pytest.raises(RuntimeError, match="simulated deletion audit failure"):
        await client.delete(
            f"/api/v1/admin/mcp/connections/{grant.id}",
            headers={"Authorization": f"Bearer {dashboard}"},
        )
    await session.refresh(grant)
    assert grant.revoked_at is None and grant.revocation_reason is None
    assert (
        await session.scalar(
            select(func.count())
            .select_from(AuditLogModel)
            .where(AuditLogModel.action == "mcp.connection_removed")
        )
        == 0
    )
