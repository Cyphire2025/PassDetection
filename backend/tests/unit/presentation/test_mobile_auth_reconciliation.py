from __future__ import annotations

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
    assert "whatsapp_broadcast_recipients" in sql
    assert "client_group_whatsapp_broadcast_links" in sql
    assert "passport_submissions" in sql
    assert "regexp_replace" in sql
    assert "gc_group_access" in sql
    assert "client_groups" in sql
    assert "passenger_access_enabled IS true" in sql
    assert "is_enabled IS true" in sql
    assert "LIMIT 20" in sql
    assert phone in sql
    assert sql.count("FOR UPDATE") == 2
