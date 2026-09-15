from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.security.mobile_jwt import hash_mobile_lookup
from app.presentation.api.v1.routes.mobile_auth import _reconcile_phone_candidate_groups


@pytest.mark.asyncio
async def test_phone_candidate_reconciliation_is_bounded_and_gc_scoped() -> None:
    scalar_result = MagicMock()
    scalar_result.unique.return_value = []
    candidate_result = MagicMock()
    candidate_result.scalars.return_value = scalar_result
    session = MagicMock()
    session.execute = AsyncMock(return_value=candidate_result)
    phone = "+919876543210"

    await _reconcile_phone_candidate_groups(
        session,
        normalized_phone=phone,
        phone_lookup_hash=hash_mobile_lookup(phone, purpose="passenger-phone"),
    )

    statements = [
        str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        for call in session.execute.await_args_list
    ]
    sql = "\n".join(statements)
    assert "whatsapp_broadcast_recipients" not in sql
    assert "client_group_whatsapp_broadcast_links" not in sql
    assert "passport_submissions" in sql
    assert "regexp_replace" in sql
    assert "gc_group_access" in sql
    assert "client_groups" in sql
    assert "client_reviewed_at IS NOT NULL" in sql
    assert "LIMIT 101" in sql
    assert "mobile_passenger_identities.phone_lookup_hash" in sql
    assert sql.count("FOR UPDATE") == 1


@pytest.mark.asyncio
async def test_already_known_legacy_binding_is_reconciled_instead_of_skipped(monkeypatch):
    from app.presentation.api.v1.routes import mobile_auth_otp_support as module

    access = SimpleNamespace(id=uuid.uuid4(), updated_by_user_id=None, created_by_user_id=None)
    monkeypatch.setattr(module, "submitted_phone_rows", AsyncMock(return_value=[]))
    reconcile = AsyncMock()
    monkeypatch.setattr(module, "reconcile_passenger_identities", reconcile)
    result = MagicMock()
    result.scalars.return_value.unique.return_value = [access]
    session = MagicMock(execute=AsyncMock(return_value=result))
    await module._reconcile_phone_candidate_groups(session, normalized_phone="+919876543210", phone_lookup_hash="legacy-hash")
    reconcile.assert_awaited_once_with(session, access=access, actor_user_id=None)
