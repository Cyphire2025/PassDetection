"""Database behavior for unexposed MCP operation primitives (no provider calls)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
    MCPOperationProgress,
    MCPOperationService,
)
from app.core.config.mcp import MCPSettings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel, MCPTokenModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import AgencyModel, UserModel, UserSecurityStateModel

POLICY = MCPToolPolicy("test.create_agency", MCPCapability.CHANGE, frozenset({"create"}))
KEY = "stable-business-key-001"


async def seed_identity(session, settings, *, email="operation-admin@example.test"):
    now = datetime.now(UTC)
    user = UserModel(
        id=uuid.uuid4(),
        email=email,
        full_name="Operation administrator",
        hashed_password="fixture",
        role="super_admin",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    session.add(
        UserSecurityStateModel(
            user_id=user.id,
            session_version=1,
            credential_state="active",
            mfa_enabled_at=now,
            mfa_secret_ciphertext="fixture",
        )
    )
    grants, tokens = [], []
    for index in range(2):
        grant = MCPGrantModel(
            id=uuid.uuid4(),
            user_id=user.id,
            client_id="global-connects-desktop",
            name=f"Fixture {index}",
            resource=settings.mcp.resource,
            capabilities=["mcp:change"],
            security_version=1,
            mfa_at=now,
            created_at=now,
            expires_at=now + timedelta(days=7),
        )
        session.add(grant)
        await session.flush()
        token = "gcmcp_access_" + uuid.uuid4().hex
        session.add(
            MCPTokenModel(
                token_hash=MCPAuthorizationService(session, settings).digest(token),
                grant_id=grant.id,
                kind="access",
                created_at=now,
                expires_at=now + timedelta(minutes=15),
            )
        )
        grants.append(grant)
        tokens.append(token)
    await session.flush()
    return user, grants, tokens


@pytest.fixture
async def operations_fixture(db_session, test_settings):
    settings = test_settings.model_copy(update={"mcp": MCPSettings(enabled=True)})
    db_session.add(MCPControlModel(id=1, enabled=True))
    user, grants, tokens = await seed_identity(db_session, settings)
    await db_session.commit()
    # sqlite's legacy driver does not BEGIN on SELECT. Force a real outer
    # transaction so savepoint rollback tests have PostgreSQL-like semantics.
    await db_session.execute(text("BEGIN"))
    return db_session, settings, user, grants, tokens


async def create_agency(context, payload):
    agency = AgencyModel(
        id=uuid.uuid4(), name=payload["name"], email=f"{uuid.uuid4()}@example.test"
    )
    context.session.add(agency)
    await context.session.flush()
    return MCPDatabaseResult(
        {"agency_id": str(agency.id), "name": agency.name},
        created_entities=(
            MCPCreatedEntity("agency", str(agency.id), f"/admin/agencies/{agency.id}"),
        ),
    )


def service(fixture, callback=create_agency):
    session, settings, _, _, _ = fixture
    return MCPOperationService(session, settings, [MCPDatabaseOperation(POLICY, callback)])


async def execute(fixture, *, callback=create_agency, key=KEY, payload=None, token_index=0):
    return await service(fixture, callback).execute(
        access_token=fixture[4][token_index],
        operation_name=POLICY.name,
        idempotency_key=key,
        payload={"name": "First agency"} if payload is None else payload,
    )


async def count(session, model):
    return await session.scalar(select(func.count()).select_from(model))


async def test_replay_across_connections_is_exact_and_does_not_run_mutation(operations_fixture):
    fixture = operations_fixture
    original = await execute(fixture)
    await fixture[0].commit()
    original["data"]["name"] = "caller changed a returned object"
    replay = await execute(fixture, token_index=1)
    assert replay["data"]["name"] == "First agency"
    assert replay["operation_id"] == original["operation_id"]
    assert await count(fixture[0], AgencyModel) == 1
    row = await fixture[0].scalar(select(MCPOperationModel))
    assert row.initial_grant_id == fixture[3][0].id
    assert row.idempotency_hash != KEY and len(row.idempotency_hash) == 64
    assert "name" not in row.payload_hash


async def test_changed_payload_conflicts_but_json_key_order_does_not(operations_fixture):
    fixture = operations_fixture
    first = await execute(fixture, payload={"name": "One", "options": {"a": 1, "b": 2}})
    assert await execute(fixture, payload={"options": {"b": 2, "a": 1}, "name": "One"}) == first
    with pytest.raises(MCPOperationError, match="idempotency_conflict"):
        await execute(fixture, payload={"name": "Changed"})
    assert await count(fixture[0], AgencyModel) == 1


async def test_creation_grant_is_provenance_not_replay_authority(operations_fixture):
    fixture = operations_fixture
    original = await execute(fixture)
    fixture[3][0].revoked_at = datetime.now(UTC)
    await fixture[0].flush()
    assert await execute(fixture, token_index=1) == original
    with pytest.raises(MCPAuthError):
        await execute(fixture, token_index=0)


async def test_key_is_scoped_to_user_and_business_operation_not_connection(operations_fixture):
    fixture = operations_fixture
    first = await execute(fixture)
    _, _, tokens = await seed_identity(fixture[0], fixture[1], email="another@example.test")
    second = await service(fixture).execute(
        access_token=tokens[0],
        operation_name=POLICY.name,
        idempotency_key=KEY,
        payload={"name": "Different user"},
    )
    other_policy = MCPToolPolicy(
        "test.other_operation", MCPCapability.CHANGE, frozenset({"create"})
    )
    other = MCPOperationService(
        fixture[0], fixture[1], [MCPDatabaseOperation(other_policy, create_agency)]
    )
    third = await other.execute(
        access_token=fixture[4][0],
        operation_name=other_policy.name,
        idempotency_key=KEY,
        payload={"name": "Other operation"},
    )
    assert len({first["operation_id"], second["operation_id"], third["operation_id"]}) == 3
    assert await count(fixture[0], AgencyModel) == 3
    with pytest.raises(MCPOperationError, match="operation_not_found"):
        await service(fixture).inspect(
            access_token=tokens[0], operation_id=uuid.UUID(first["operation_id"])
        )


@pytest.mark.parametrize(
    "change",
    ["revoked", "narrowed", "expired", "role", "inactive", "security", "disabled", "token_expired"],
)
async def test_replay_and_inspection_recheck_current_authority(operations_fixture, change):
    fixture = operations_fixture
    initial = await execute(fixture)
    session, _, user, grants, tokens = fixture
    if change == "revoked":
        grants[1].revoked_at = datetime.now(UTC)
    elif change == "narrowed":
        grants[1].capabilities = ["mcp:read"]
    elif change == "expired":
        grants[1].created_at = datetime.now(UTC) - timedelta(days=8)
        grants[1].expires_at = datetime.now(UTC) - timedelta(days=1)
    elif change == "role":
        user.role = "agency_admin"
    elif change == "inactive":
        user.is_active = False
    elif change == "security":
        security = await session.get(UserSecurityStateModel, user.id)
        security.session_version += 1
    elif change == "disabled":
        (await session.get(MCPControlModel, 1)).enabled = False
    elif change == "token_expired":
        token = await session.get(
            MCPTokenModel, MCPAuthorizationService(session, fixture[1]).digest(tokens[1])
        )
        token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.flush()
    with pytest.raises(MCPAuthError):
        await execute(fixture, token_index=1)
    with pytest.raises(MCPAuthError):
        await service(fixture).inspect(
            access_token=tokens[1], operation_id=uuid.UUID(initial["operation_id"])
        )
    assert await count(session, AgencyModel) == 1


@pytest.mark.parametrize(
    "failure", ["exception", "cancelled", "commit", "rollback", "invalid_result"]
)
async def test_failed_callbacks_leave_neither_mutation_nor_receipt(operations_fixture, failure):
    fixture = operations_fixture

    async def broken(context, payload):
        await create_agency(context, payload)
        if failure == "exception":
            raise RuntimeError("callback failed")
        if failure == "cancelled":
            raise asyncio.CancelledError()
        if failure == "commit":
            await context.session.commit()
        if failure == "rollback":
            await context.session.rollback()
            return MCPDatabaseResult({"attempted": True})
        return MCPDatabaseResult({"not_json": object()})

    expected = (
        asyncio.CancelledError
        if failure == "cancelled"
        else RuntimeError
        if failure == "exception"
        else MCPOperationError
    )
    with pytest.raises(expected):
        await execute(fixture, callback=broken)
    assert await count(fixture[0], AgencyModel) == 0
    assert await count(fixture[0], MCPOperationModel) == 0
    # A failed database transaction reserves no key and has no external effect.
    assert (await execute(fixture))["status"] == "succeeded"
    assert await count(fixture[0], AgencyModel) == 1


async def test_caller_rollback_rolls_back_both_business_write_and_receipt(operations_fixture):
    fixture = operations_fixture
    await execute(fixture)
    await fixture[0].rollback()
    assert await count(fixture[0], AgencyModel) == 0
    assert await count(fixture[0], MCPOperationModel) == 0


async def test_progress_is_durable_but_never_rewrites_initial_response(operations_fixture):
    fixture = operations_fixture
    job_id = uuid.uuid4()

    async def enqueue(_context, _payload):
        return MCPDatabaseResult(
            {"accepted_job_id": str(job_id)}, status="queued", workflow_id=job_id
        )

    receipt = await execute(fixture, callback=enqueue)
    operation_id = uuid.UUID(receipt["operation_id"])
    svc = service(fixture, enqueue)
    assert (
        await svc.record_progress(
            operation_id=operation_id,
            expected_revision=1,
            update=MCPOperationProgress("running", 0.4, "parsing"),
        )
        == 2
    )
    entity = MCPCreatedEntity("agency", str(uuid.uuid4()), "/admin/agencies")
    assert (
        await svc.record_progress(
            operation_id=operation_id,
            expected_revision=2,
            update=MCPOperationProgress("unknown", 0.6, "awaiting_reconciliation", (entity,)),
        )
        == 3
    )
    assert await execute(fixture, callback=enqueue, token_index=1) == receipt
    assert (
        await svc.record_progress(
            operation_id=operation_id,
            expected_revision=3,
            update=MCPOperationProgress("failed", 0.6, "provider_failed"),
        )
        == 4
    )
    await fixture[0].commit()
    current = await svc.inspect(access_token=fixture[4][1], operation_id=operation_id)
    assert current["status"] == "failed" and current["revision"] == 4
    assert current["workflow_id"] == str(job_id) and current["completed_at"]
    assert current["created_entities"] == [entity.as_dict()]
    assert await execute(fixture, callback=enqueue) == receipt


@pytest.mark.parametrize(
    "status,progress,revision",
    [("running", 0.1, 1), ("running", 0.1, 2), ("succeeded", 0.9, 2), ("running", float("nan"), 2)],
)
async def test_stale_regressive_and_false_completion_progress_is_rejected(
    operations_fixture, status, progress, revision
):
    async def enqueue(_context, _payload):
        return MCPDatabaseResult({}, status="queued")

    receipt = await execute(operations_fixture, callback=enqueue)
    svc, op_id = service(operations_fixture, enqueue), uuid.UUID(receipt["operation_id"])
    await svc.record_progress(
        operation_id=op_id,
        expected_revision=1,
        update=MCPOperationProgress("running", 0.5, "processing"),
    )
    with pytest.raises(MCPOperationError):
        await svc.record_progress(
            operation_id=op_id,
            expected_revision=revision,
            update=MCPOperationProgress(status, progress, "processing"),
        )
    snapshot = await svc.inspect(access_token=operations_fixture[4][0], operation_id=op_id)
    assert snapshot["revision"] == 2 and snapshot["progress"] == 0.5


@pytest.mark.parametrize(
    "payload",
    [{"name": float("nan")}, {1: "key"}, {"name": object()}, {"name": "x" * (1024 * 1024)}],
)
async def test_invalid_payload_never_invokes_callback(operations_fixture, payload):
    with pytest.raises(MCPOperationError, match="invalid_operation_json"):
        await execute(operations_fixture, payload=payload)
    assert await count(operations_fixture[0], MCPOperationModel) == 0


async def test_empty_registration_and_forbidden_effects_fail_closed(operations_fixture):
    empty = MCPOperationService(operations_fixture[0], operations_fixture[1])
    with pytest.raises(MCPOperationError, match="unsupported_operation"):
        await empty.execute(
            access_token=operations_fixture[4][0],
            operation_name=POLICY.name,
            idempotency_key=KEY,
            payload={"name": "Should not run"},
        )
    with pytest.raises(ValueError, match="Forbidden MCP effects"):
        MCPOperationService(
            operations_fixture[0],
            operations_fixture[1],
            [
                MCPDatabaseOperation(
                    MCPToolPolicy("test.delete", MCPCapability.CHANGE, frozenset({"delete"})),
                    create_agency,
                )
            ],
        )
    assert await count(operations_fixture[0], AgencyModel) == 0


async def test_terminal_completion_and_links_cannot_be_rewritten(operations_fixture):
    fixture = operations_fixture
    receipt = await execute(fixture)
    operation_id = uuid.UUID(receipt["operation_id"])
    with pytest.raises(MCPOperationError, match="invalid_workflow_transition"):
        await service(fixture).record_progress(
            operation_id=operation_id,
            expected_revision=1,
            update=MCPOperationProgress("running", 1, "restart"),
        )
    assert (await service(fixture).inspect(access_token=fixture[4][0], operation_id=operation_id))[
        "status"
    ] == "succeeded"


@pytest.mark.parametrize(
    "path",
    [
        "https://untrusted.test/",
        "//untrusted.test/",
        "/admin/../login",
        "/admin?token=secret",
        "/admin\\redirect",
    ],
)
async def test_created_links_remain_plain_application_paths(operations_fixture, path):
    async def bad_link(context, payload):
        result = await create_agency(context, payload)
        return MCPDatabaseResult(
            result.data, created_entities=(MCPCreatedEntity("agency", "fixture", path),)
        )

    with pytest.raises(MCPOperationError, match="invalid_created_entity"):
        await execute(operations_fixture, callback=bad_link)
    assert await count(operations_fixture[0], AgencyModel) == 0
    assert await count(operations_fixture[0], MCPOperationModel) == 0


@pytest.mark.parametrize("inspection", [False, True])
async def test_receipt_access_callback_cannot_commit_or_mutate_saved_response(
    operations_fixture, inspection
):
    fixture = operations_fixture
    original = await execute(fixture)
    await fixture[0].commit()

    async def invalid_authorizer(context, receipt):
        receipt["data"]["name"] = "attempted response mutation"
        await context.session.commit()

    svc = MCPOperationService(
        fixture[0], fixture[1], [MCPDatabaseOperation(POLICY, create_agency, invalid_authorizer)]
    )
    with pytest.raises(MCPOperationError, match="callback_must_not_commit"):
        if inspection:
            await svc.inspect(
                access_token=fixture[4][1], operation_id=uuid.UUID(original["operation_id"])
            )
        else:
            await svc.execute(
                access_token=fixture[4][1],
                operation_name=POLICY.name,
                idempotency_key=KEY,
                payload={"name": "First agency"},
            )
    await fixture[0].rollback()
    assert await execute(fixture) == original
