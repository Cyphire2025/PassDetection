from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.security.destructive_mutation_policy import (
    DestructiveMutationPolicy,
    DestructiveOwnedGroupsMutation,
    destructive_request_fingerprint,
    record_destructive_failure,
)
from app.domain.entities.entities import ClientGroup, User, UserRole
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    EntityNotFoundError,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository


class _AsyncSessionContext:
    def __init__(self, session: object) -> None:
        self._session = session

    async def __aenter__(self) -> object:
        return self._session

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        return None


def _agency_admin(agency_id: uuid.UUID) -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.com",
        hashed_password="unused",
        full_name="Agency Admin",
        role=UserRole.AGENCY_ADMIN,
        agency_id=agency_id,
    )


def _super_admin() -> User:
    return User(
        id=uuid.uuid4(),
        email="root@example.com",
        hashed_password="unused",
        full_name="Root Admin",
        role=UserRole.SUPER_ADMIN,
        agency_id=None,
    )


def _group(*, agency_id: uuid.UUID, held: bool = False) -> ClientGroup:
    group = ClientGroup.create(
        name="Protected Group",
        token=str(uuid.uuid4()),
        agency_id=agency_id,
        created_by_user_id=uuid.uuid4(),
    )
    group.passport_legal_hold = held
    if held:
        group.passport_legal_hold_reason = "Sensitive legal reason that must not be audited"
    return group


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_scope", ["group", "submissions"])
async def test_locked_policy_ignores_legacy_hold_and_preserves_tenant_scope(delete_scope) -> None:
    agency_id = uuid.uuid4()
    group = _group(agency_id=agency_id, held=True)
    user = _agency_admin(agency_id)
    session = SimpleNamespace(commit=AsyncMock())
    load_group = AsyncMock(return_value=group)
    audit = AsyncMock(return_value=None)

    with (
        patch.object(ClientGroupRepository, "get_by_id_for_update", load_group),
        patch.object(AuditLogRepository, "record", audit),
    ):
        context = await DestructiveMutationPolicy(session).require_group(
            user=user,
            group_id=group.id,
            action="passport_submissions_bulk_delete",
            target_ids=[uuid.uuid4()],
            delete_scope=delete_scope,
        )

    assert context.group is group
    load_group.assert_awaited_once_with(
        group.id,
        agency_id=agency_id,
        allow_global_scope=False,
    )
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["action"] == "destructive_operation_attempted"
    assert "Sensitive legal reason" not in repr(audit.await_args.kwargs["metadata"])
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_locked_policy_hides_cross_tenant_group_existence() -> None:
    user = _agency_admin(uuid.uuid4())
    session = SimpleNamespace(commit=AsyncMock())
    load_group = AsyncMock(return_value=None)
    authorize = AsyncMock()
    audit = AsyncMock()

    with (
        patch.object(ClientGroupRepository, "get_by_id_for_update", load_group),
        patch.object(AuthorizationPolicy, "require_delete_data", authorize),
        patch.object(AuditLogRepository, "record", audit),
        pytest.raises(EntityNotFoundError),
    ):
        await DestructiveMutationPolicy(session).require_group(
            user=user,
            group_id=uuid.uuid4(),
            action="client_group_permanent_delete",
        )

    authorize.assert_not_awaited()
    audit.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_locked_policy_persists_privacy_safe_denied_attempt() -> None:
    agency_id = uuid.uuid4()
    group = _group(agency_id=agency_id, held=True)
    user = _agency_admin(agency_id)
    user.role = UserRole.AGENCY_MANAGER
    session = SimpleNamespace(commit=AsyncMock())
    audit = AsyncMock(return_value=None)

    with (
        patch.object(
            ClientGroupRepository,
            "get_by_id_for_update",
            AsyncMock(return_value=group),
        ),
        patch.object(AuditLogRepository, "record", audit),
        pytest.raises(AuthorizationError),
    ):
        await DestructiveMutationPolicy(session).require_group(
            user=user,
            group_id=group.id,
            action="client_group_permanent_delete",
        )

    assert audit.await_count == 2
    denied = audit.await_args_list[1].kwargs
    assert denied["result"] == "denied"
    assert denied["metadata"]["reason_code"] == "AUTHORIZATION_ERROR"
    assert group.name not in repr(denied["metadata"])
    session.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_manager_owned_delete_ignores_legacy_holds_and_keeps_ordered_scope() -> None:
    agency_id = uuid.uuid4()
    manager_id = uuid.uuid4()
    groups = [
        _group(agency_id=agency_id),
        _group(agency_id=agency_id, held=True),
    ]
    session = SimpleNamespace(commit=AsyncMock())
    load_groups = AsyncMock(return_value=groups)
    audit = AsyncMock(return_value=None)

    with (
        patch.object(ClientGroupRepository, "list_owned_for_update", load_groups),
        patch.object(AuditLogRepository, "record", audit),
    ):
        context = await DestructiveMutationPolicy(session).require_manager_owned_groups(
            user=_super_admin(),
            manager_id=manager_id,
            manager_agency_id=agency_id,
            action="manager_owned_passport_data_delete",
        )

    load_groups.assert_awaited_once_with(
        owner_user_id=manager_id,
        agency_id=agency_id,
    )
    assert context.groups == tuple(groups)
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["metadata"]["group_count"] == 2
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("global_scope", [False, True])
async def test_scoped_purge_ignores_legacy_holds_without_widening_scope(global_scope) -> None:
    agency_id = uuid.uuid4()
    groups = (
        _group(agency_id=agency_id),
        _group(agency_id=agency_id, held=True),
    )
    user = _super_admin() if global_scope else _agency_admin(agency_id)
    session = SimpleNamespace(commit=AsyncMock())
    load_groups = AsyncMock(return_value=list(groups))
    audit = AsyncMock(return_value=None)

    with (
        patch.object(ClientGroupRepository, "list_scope_for_update", load_groups),
        patch.object(AuditLogRepository, "record", audit),
    ):
        context = await DestructiveMutationPolicy(session).require_scoped_groups(
            user=user,
            action="passport_data_purge",
        )

    load_groups.assert_awaited_once_with(
        agency_id=None if global_scope else agency_id,
        allow_global_scope=global_scope,
    )
    assert context.groups == groups
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["metadata"]["group_count"] == 2
    assert "Sensitive legal reason" not in repr(audit.await_args.kwargs["metadata"])
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["tenant", "manager_owned"])
async def test_manager_cannot_authorize_administrative_purge(scope: str) -> None:
    agency_id = uuid.uuid4()
    user = _agency_admin(agency_id)
    user.role = UserRole.AGENCY_MANAGER
    session = SimpleNamespace(commit=AsyncMock())
    with (
        patch.object(ClientGroupRepository, "list_scope_for_update", AsyncMock()) as load_scope,
        patch.object(ClientGroupRepository, "list_owned_for_update", AsyncMock()) as load_owned,
        patch.object(AuditLogRepository, "record", AsyncMock()) as audit,
        pytest.raises(AuthorizationError),
    ):
        policy = DestructiveMutationPolicy(session)
        if scope == "tenant":
            await policy.require_scoped_groups(user=user, action="passport_data_purge")
        else:
            await policy.require_manager_owned_groups(
                user=user, manager_id=user.id, manager_agency_id=agency_id,
                action="manager_owned_passport_data_delete",
            )
    load_scope.assert_not_awaited()
    load_owned.assert_not_awaited()
    audit.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_repository_locked_lookup_has_tenant_predicate_and_for_update() -> None:
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()

    loaded = await ClientGroupRepository(session).get_by_id_for_update(
        group_id,
        agency_id=agency_id,
    )

    assert loaded is None
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "client_groups.id" in sql
    assert "client_groups.agency_id" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_repository_owned_group_locks_are_tenant_scoped_and_deterministic() -> None:
    scalar_result = SimpleNamespace(all=lambda: [])
    result = SimpleNamespace(scalars=lambda: scalar_result)
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    agency_id = uuid.uuid4()
    manager_id = uuid.uuid4()

    loaded = await ClientGroupRepository(session).list_owned_for_update(
        owner_user_id=manager_id,
        agency_id=agency_id,
    )

    assert loaded == []
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "client_groups.created_by_user_id" in sql
    assert "client_groups.agency_id" in sql
    assert "ORDER BY client_groups.id" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agency_id", "allow_global_scope", "expects_tenant_predicate"),
    [
        (uuid.uuid4(), False, True),
        (None, True, False),
    ],
)
async def test_repository_purge_scope_locks_are_ordered_and_explicit(
    agency_id: uuid.UUID | None,
    allow_global_scope: bool,
    expects_tenant_predicate: bool,
) -> None:
    scalar_result = SimpleNamespace(all=lambda: [])
    result = SimpleNamespace(scalars=lambda: scalar_result)
    session = SimpleNamespace(execute=AsyncMock(return_value=result))

    loaded = await ClientGroupRepository(session).list_scope_for_update(
        agency_id=agency_id,
        allow_global_scope=allow_global_scope,
    )

    assert loaded == []
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert ("WHERE client_groups.agency_id" in sql) is expects_tenant_predicate
    assert "ORDER BY client_groups.id" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_repository_refuses_implicit_global_purge_scope() -> None:
    session = SimpleNamespace(execute=AsyncMock())

    loaded = await ClientGroupRepository(session).list_scope_for_update(
        agency_id=None,
    )

    assert loaded == []
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_commit_failure_uses_fresh_privacy_safe_audit_transaction() -> None:
    manager_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    user = _super_admin()
    audit_session = SimpleNamespace(commit=AsyncMock())
    audit_record = AsyncMock(return_value=None)
    context = DestructiveOwnedGroupsMutation(
        manager_id=manager_id,
        groups=(_group(agency_id=agency_id),),
        action="manager_owned_passport_data_delete",
        request_fingerprint="f" * 64,
    )

    with patch.object(AuditLogRepository, "record", audit_record):
        recorded = await record_destructive_failure(
            context,
            user=user,
            error=RuntimeError("database URL and sensitive value must not be recorded"),
            session_factory=lambda: _AsyncSessionContext(audit_session),
        )

    assert recorded is True
    audit_record.assert_awaited_once()
    assert audit_record.await_args.kwargs["entity_id"] == str(manager_id)
    assert audit_record.await_args.kwargs["agency_id"] == agency_id
    assert audit_record.await_args.kwargs["result"] == "failed"
    metadata = audit_record.await_args.kwargs["metadata"]
    assert metadata["reason_code"] == "RuntimeError"
    assert "database URL" not in repr(metadata)
    audit_session.commit.assert_awaited_once_with()


def test_destructive_request_fingerprint_is_stable_and_order_independent() -> None:
    entity_id = uuid.uuid4()
    first_target = uuid.uuid4()
    second_target = uuid.uuid4()

    first = destructive_request_fingerprint(
        action="passport_submissions_bulk_delete",
        entity_id=entity_id,
        target_ids=[first_target, second_target, first_target],
    )
    second = destructive_request_fingerprint(
        action="passport_submissions_bulk_delete",
        entity_id=entity_id,
        target_ids=[second_target, first_target],
    )

    assert first == second
    assert len(first) == 64
    assert str(first_target) not in first
