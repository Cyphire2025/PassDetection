from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)


class _ScalarResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


@pytest.mark.asyncio
async def test_platform_duplicate_contact_check_serializes_every_contact() -> None:
    duplicate_id = uuid.uuid4()
    execute = AsyncMock(
        side_effect=[
            _ScalarResult(None),
            _ScalarResult(None),
            _ScalarResult(None),
            _ScalarResult(None),
            _ScalarResult(duplicate_id),
        ]
    )
    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        execute=execute,
    )
    repository = PassportSubmissionRepository(session)  # type: ignore[arg-type]

    exists = await repository.exists_contact_in_group(
        uuid.uuid4(),
        client_email="head@example.com",
        client_phone="9000022222",
        additional_emails=("member@example.com",),
        additional_phones=("9000011111",),
        scope="platform",
        exclude_submission_id=uuid.uuid4(),
    )

    assert exists is True
    assert execute.await_count == 5
    for lock_call in execute.await_args_list[:4]:
        assert "pg_advisory_xact_lock" in str(lock_call.args[0])
    duplicate_query = str(execute.await_args_list[-1].args[0])
    assert "family_head_email" in duplicate_query
    assert "family_head_phone" in duplicate_query
    assert "passport_submissions.group_id =" not in duplicate_query


@pytest.mark.asyncio
async def test_same_group_duplicate_policy_stays_group_scoped_on_sqlite() -> None:
    execute = AsyncMock(return_value=_ScalarResult(None))
    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
        execute=execute,
    )
    repository = PassportSubmissionRepository(session)  # type: ignore[arg-type]

    exists = await repository.exists_contact_in_group(
        uuid.uuid4(),
        client_email="person@example.com",
        client_phone=None,
    )

    assert exists is False
    execute.assert_awaited_once()
    assert "passport_submissions.group_id =" in str(execute.await_args.args[0])
