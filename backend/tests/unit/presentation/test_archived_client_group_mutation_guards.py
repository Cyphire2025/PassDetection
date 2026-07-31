from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.presentation.api.v1.routes import client_groups


@pytest.mark.asyncio
async def test_mutable_group_guard_locks_exact_current_tenant_group() -> None:
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    result = SimpleNamespace(scalar_one_or_none=lambda: group.id)
    session = SimpleNamespace(execute=AsyncMock(return_value=result))

    await client_groups._require_mutable_client_group(session, group)

    sql = str(
        session.execute.await_args.args[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert f"client_groups.id = '{group.id}'" in sql
    assert f"client_groups.agency_id = '{group.agency_id}'" in sql
    assert "client_groups.status IN ('active', 'closed')" in sql
    assert "client_groups.deleted_at IS NULL" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_mutable_group_guard_fails_closed() -> None:
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    session = SimpleNamespace(execute=AsyncMock(return_value=result))

    with pytest.raises(HTTPException) as exc_info:
        await client_groups._require_mutable_client_group(session, group)

    assert exc_info.value.status_code == 409
    assert "read-only" in str(exc_info.value.detail)


def test_group_page_write_routes_require_the_locked_mutability_guard() -> None:
    managed_guard_routes = (
        client_groups.replace_client_group_whatsapp_links,
        client_groups.resolve_unidentified_as_replacement,
        client_groups.reject_unidentified_upload,
        client_groups.restore_roster_resolution,
    )
    for route in managed_guard_routes:
        assert "require_mutable=True" in inspect.getsource(route)

    direct_guard_routes = (
        client_groups.revoke_client_group,
        client_groups.update_client_group,
        client_groups.delete_client_group,
    )
    for route in direct_guard_routes:
        assert "_require_mutable_client_group" in inspect.getsource(route)
