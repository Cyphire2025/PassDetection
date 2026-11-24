"""Execute administrative deletion selections against isolated persisted rows."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AgencyModel, ClientGroupModel, NotificationModel
from app.presentation.api.v1.routes.admin_deletion_queries import (
    _delete_by_ids,
    _delete_entity_rows,
)
from tests.integration.test_admin_workforce_contracts import _actor
from tests.persistence import persist_graph


@pytest.mark.parametrize("platform_scope", [False, True])
@pytest.mark.parametrize("selection", ["group", "submission", "both"])
async def test_notification_cleanup_matches_both_entity_kind_and_authorized_scope(
    db_session: AsyncSession,
    platform_scope: bool,
    selection: str,
) -> None:
    actor = await _actor(db_session)
    assert actor.agency_id is not None
    foreign_agency_id = uuid.uuid4()
    group_id, submission_id, unrelated_id = (str(uuid.uuid4()) for _ in range(3))
    identities = [uuid.uuid4() for _ in range(5)]
    await persist_graph(
        db_session,
        [
            AgencyModel(
                id=foreign_agency_id, name="Synthetic other agency", email="other@example.com"
            ),
            *[
                NotificationModel(
                    id=row_id,
                    agency_id=agency_id,
                    type="synthetic-test",
                    title="Synthetic notification",
                    message="No personal data",
                    entity_type=kind,
                    entity_id=entity_id,
                )
                for row_id, agency_id, kind, entity_id in [
                    (identities[0], actor.agency_id, "client_group", group_id),
                    (identities[1], actor.agency_id, "passport_submission", submission_id),
                    (identities[2], foreign_agency_id, "client_group", group_id),
                    (identities[3], actor.agency_id, "client_group", unrelated_id),
                    (identities[4], actor.agency_id, "unrelated_entity", group_id),
                ]
            ],
        ],
    )
    selected: set[uuid.UUID] = set()
    if selection in {"group", "both"}:
        selected.add(identities[0])
        if platform_scope:
            selected.add(identities[2])
    if selection in {"submission", "both"}:
        selected.add(identities[1])
    deleted = await _delete_entity_rows(
        db_session,
        NotificationModel,
        agency_id=None if platform_scope else actor.agency_id,
        group_entity_ids=[group_id] if selection in {"group", "both"} else [],
        submission_entity_ids=[submission_id] if selection in {"submission", "both"} else [],
    )
    assert deleted == len(selected)
    assert set(await db_session.scalars(select(NotificationModel.id))) == set(identities) - selected


async def test_group_delete_count_covers_only_the_explicit_locked_ids(
    db_session: AsyncSession,
) -> None:
    actor = await _actor(db_session)
    selected, retained = uuid.uuid4(), uuid.uuid4()
    await persist_graph(
        db_session,
        [
            ClientGroupModel(
                id=group_id,
                agency_id=actor.agency_id,
                name="Synthetic group",
                token=uuid.uuid4().hex,
                created_by_user_id=actor.id,
            )
            for group_id in (selected, retained)
        ],
    )
    assert (
        await _delete_by_ids(
            db_session, ClientGroupModel, ClientGroupModel.id, [selected, uuid.uuid4()]
        )
        == 1
    )
    assert set(await db_session.scalars(select(ClientGroupModel.id))) == {retained}


async def test_empty_cleanup_selections_never_dispatch_a_delete() -> None:
    session = SimpleNamespace(execute=AsyncMock())
    assert await _delete_by_ids(session, ClientGroupModel, ClientGroupModel.id, []) == 0
    assert (
        await _delete_entity_rows(
            session,
            NotificationModel,
            agency_id=None,
            group_entity_ids=[],
            submission_entity_ids=[],
        )
        == 0
    )
    session.execute.assert_not_awaited()
