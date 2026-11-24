"""Upload-link facade boundaries without providers or external storage."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes import client_groups


@pytest.mark.asyncio
async def test_retention_rejects_unscoped_or_missing_groups_before_mutation() -> None:
    for route in (
        client_groups.revoke_client_group,
        client_groups.delete_client_group,
        client_groups.restore_client_group,
    ):
        session = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)
        use_case = SimpleNamespace(execute=AsyncMock())
        user = SimpleNamespace(id=uuid.uuid4(), agency_id=None)
        identifier = uuid.uuid4()
        with pytest.raises(HTTPException) as unscoped:
            await route(identifier, current_user=user, use_case=use_case, session=session)
        assert unscoped.value.status_code == 403
        session.execute.assert_not_awaited()
        use_case.execute.assert_not_awaited()

        user.agency_id = uuid.uuid4()
        with pytest.raises(HTTPException) as missing:
            await route(identifier, current_user=user, use_case=use_case, session=session)
        assert missing.value.status_code == 404
        session.execute.assert_awaited_once()
        use_case.execute.assert_not_awaited()
        session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_group_listing_preserves_agency_and_deleted_data_visibility() -> None:
    use_case = SimpleNamespace(execute=AsyncMock(return_value=[]))
    user = SimpleNamespace(id=uuid.uuid4(), agency_id=None, role=UserRole.AGENCY_STAFF)
    arguments = dict(skip=4, limit=7, current_user=user, use_case=use_case)
    assert await client_groups.list_client_groups(status_filter=None, **arguments) == []
    use_case.execute.assert_not_awaited()
    user.agency_id = uuid.uuid4()
    with pytest.raises(HTTPException) as forbidden:
        await client_groups.list_client_groups(status_filter="deleted", **arguments)
    assert forbidden.value.status_code == 403
    use_case.execute.assert_not_awaited()

    assert await client_groups.list_client_groups(status_filter=None, **arguments) == []
    use_case.execute.assert_awaited_once_with(
        agency_id=user.agency_id,
        skip=4,
        limit=7,
        status_filter=None,
        created_by_user_id=user.id,
        visible_to_user=user,
    )
    use_case.execute.reset_mock()
    user.role = UserRole.SUPER_ADMIN
    assert await client_groups.list_client_groups(status_filter="deleted", **arguments) == []
    use_case.execute.assert_awaited_once_with(
        agency_id=user.agency_id,
        skip=4,
        limit=7,
        status_filter="deleted",
        created_by_user_id=None,
        visible_to_user=None,
    )


@pytest.mark.asyncio
async def test_replacement_candidates_merge_same_person_across_linked_broadcasts() -> None:
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    first_broadcast, second_broadcast = uuid.uuid4(), uuid.uuid4()
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    recipients = [
        SimpleNamespace(
            id=second_id,
            broadcast_group_id=second_broadcast,
            normalized_phone_number="+919876543210",
            name="Traveller",
            imported_fields={"office": "B"},
        ),
        SimpleNamespace(
            id=first_id,
            broadcast_group_id=first_broadcast,
            normalized_phone_number="9876543210",
            name=None,
            imported_fields={"office": "A"},
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            broadcast_group_id=first_broadcast,
            normalized_phone_number="invalid",
            name="Invalid",
            imported_fields={},
        ),
    ]
    result = MagicMock()
    result.scalars.return_value.all.return_value = recipients
    session = MagicMock(execute=AsyncMock(return_value=result))
    with (
        patch.object(client_groups, "_require_whatsapp_broadcast_access"),
        patch.object(client_groups, "_require_managed_group", AsyncMock(return_value=group)),
        patch.object(
            client_groups,
            "_linked_broadcast_names_for_group",
            AsyncMock(
                return_value={
                    first_broadcast: "Alpha",
                    second_broadcast: "Beta",
                }
            ),
        ),
    ):
        response = await client_groups.list_replacement_candidates(
            group.id,
            current_user=SimpleNamespace(id=uuid.uuid4()),
            session=session,
        )
    assert response.client_group_id == group.id
    assert len(response.items) == 1
    item = response.items[0]
    assert item.recipient_id == first_id
    assert item.recipient_ids == [first_id, second_id]
    assert item.name == "Traveller" and item.phone == "+919876543210"
    assert item.broadcast_names == ["Alpha", "Beta"]
    assert item.imported_fields == {"office": "A"}
    statement = session.execute.await_args.args[0]
    assert "agency_id" in str(statement)
    assert "removed_at IS NULL" in str(statement)
    assert "suppressed_by_roster_resolution_id IS NULL" in str(statement)
