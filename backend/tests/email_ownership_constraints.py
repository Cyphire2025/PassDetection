"""Identical adversarial inserts for SQLite metadata and migrated PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.infrastructure.database.models import AgencyModel, UserModel
from tests.persistence import persist_graph

CASES = ("missing_connection", "wrong_agency", "wrong_owner")


async def assert_email_parent_constraint(session: AsyncSession, case: str) -> None:
    """Reject real FK violations while retaining a valid control in the transaction."""
    assert case in CASES
    agency_id, other_agency_id, owner_id, other_owner_id = (uuid.uuid4() for _ in range(4))
    connection_id, valid_id, rejected_id = (uuid.uuid4() for _ in range(3))
    await persist_graph(session, [
        AgencyModel(id=agency_id, name="Constraint owner", email=f"{agency_id}@example.test"),
        AgencyModel(id=other_agency_id, name="Other tenant", email=f"{other_agency_id}@example.test"),
        *[UserModel(
            id=user_id, agency_id=agency_id, full_name="Synthetic owner",
            email=f"{user_id}@example.test", hashed_password="unused-synthetic-hash",
            role="agency_staff",
        ) for user_id in (owner_id, other_owner_id)],
        EmailConnectionModel(
            id=connection_id, agency_id=agency_id, owner_user_id=owner_id,
            provider="gmail", provider_account_id=str(connection_id),
            email_address=f"{connection_id}@example.test",
        ),
    ])

    def message(identifier: uuid.UUID, **changes: uuid.UUID) -> EmailMessageModel:
        scope = {"connection_id": connection_id, "agency_id": agency_id, "owner_user_id": owner_id}
        scope.update(changes)
        return EmailMessageModel(
            id=identifier, **scope, provider_message_id=str(identifier),
            received_at=datetime.now(UTC),
        )

    session.add(message(valid_id))
    await session.flush()
    changes = {
        "missing_connection": {"connection_id": uuid.uuid4()},
        # Both alternative parents exist: standalone id FKs cannot reject these.
        "wrong_agency": {"agency_id": other_agency_id},
        "wrong_owner": {"owner_user_id": other_owner_id},
    }[case]
    with pytest.raises(IntegrityError) as failure:
        async with session.begin_nested():
            session.add(message(rejected_id, **changes))
            await session.flush()

    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        assert getattr(failure.value.orig, "sqlstate", None) == "23503"
        if case == "wrong_owner":
            assert "fk_email_messages_connection_agency_owner" in str(failure.value.orig)
    else:
        assert dialect == "sqlite"
        assert getattr(failure.value.orig, "sqlite_errorname", None) == "SQLITE_CONSTRAINT_FOREIGNKEY"
    # An unrelated NOT NULL/unique error cannot make the test pass, and the
    # failed insert's rollback must neither delete nor corrupt the valid control.
    assert await session.scalar(select(EmailMessageModel.id).where(EmailMessageModel.id == valid_id)) == valid_id
    assert await session.scalar(select(EmailMessageModel.id).where(EmailMessageModel.id == rejected_id)) is None
    control = await session.get(EmailMessageModel, valid_id)
    assert control is not None
    assert (control.connection_id, control.agency_id, control.owner_user_id) == (connection_id, agency_id, owner_id)
