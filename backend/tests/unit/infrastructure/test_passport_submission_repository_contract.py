"""Runtime facade contracts and transaction boundaries used by repository callers."""

from __future__ import annotations

import inspect
import uuid
from dataclasses import replace
from typing import get_args, get_origin, get_type_hints
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from app.domain.repositories.interfaces import IPassportSubmissionRepository
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.repositories import passport_submission_mapping, passport_submission_queries
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from tests.unit.application.test_traveller_enrollment import _fixture


def _hint_structure(annotation):
    # The existing port uses typing.Sequence; the implementation has always
    # used collections.abc.Sequence. Compare their resolved generic contracts.
    origin = get_origin(annotation)
    return (
        (origin, tuple(_hint_structure(arg) for arg in get_args(annotation)))
        if origin
        else annotation
    )


def test_public_repository_signatures_and_hints_match_the_domain_port() -> None:
    session = AsyncMock()
    repository = PassportSubmissionRepository(session)
    assert repository._session is session
    assert not inspect.isabstract(PassportSubmissionRepository)
    assert get_type_hints(PassportSubmissionRepository.__init__)["return"] is type(None)
    for name in IPassportSubmissionRepository.__abstractmethods__:
        actual = getattr(PassportSubmissionRepository, name)
        contract = getattr(IPassportSubmissionRepository, name)
        assert inspect.signature(actual) == inspect.signature(contract), name
        assert {key: _hint_structure(value) for key, value in get_type_hints(actual).items()} == {
            key: _hint_structure(value) for key, value in get_type_hints(contract).items()
        }, name
        assert inspect.iscoroutinefunction(actual), name


def test_private_mapping_and_scope_aliases_resolve_actual_types_and_functions() -> None:
    for owner, names in (
        (passport_submission_mapping, ("_to_entity", "_to_model", "_apply_extraction_fields")),
        (
            passport_submission_queries,
            ("_office_visible_statuses", "_status_filter_values", "_apply_manager_group_scope"),
        ),
    ):
        for name in names:
            actual = getattr(PassportSubmissionRepository, name)
            assert actual is getattr(owner, name)
            assert get_type_hints(actual) == get_type_hints(getattr(owner, name))
    for name in ("_agency_scope", "_group_scope", "_apply_search"):
        assert get_type_hints(getattr(PassportSubmissionRepository, name)) == get_type_hints(
            getattr(passport_submission_queries, name)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("detach_fails", [False, True])
async def test_delete_preserves_provenance_order_and_the_callers_transaction(detach_fails) -> None:
    submission_id = uuid.uuid4()
    steps = []

    async def detach(session, ids):
        assert session is db and ids == [submission_id]
        steps.append("detach")
        if detach_fails:
            raise RuntimeError("synthetic provenance failure")

    async def execute(statement):
        steps.append("delete")
        compiled = str(
            statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )
        assert compiled.startswith("DELETE FROM passport_submissions")
        assert str(submission_id) in compiled

    async def flush():
        steps.append("flush")

    db = AsyncMock()
    db.execute.side_effect, db.flush.side_effect = execute, flush
    with patch(
        "app.application.travellers.retention.detach_submission_provenance", side_effect=detach
    ):
        if detach_fails:
            with pytest.raises(RuntimeError, match="synthetic provenance failure"):
                await PassportSubmissionRepository(db).delete(submission_id)
        else:
            await PassportSubmissionRepository(db).delete(submission_id)
    assert steps == (["detach"] if detach_fails else ["detach", "delete", "flush"])
    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_idempotent_collision_keeps_outer_transaction_and_first_submission(
    db_session,
) -> None:
    context = await _fixture(db_session)
    original = PassportSubmissionRepository._to_entity(context.source)
    first = replace(original, id=uuid.uuid4(), upload_idempotency_key="synthetic-logical-upload")
    duplicate = replace(first, id=uuid.uuid4(), client_name="Later duplicate payload")
    independent = replace(first, id=uuid.uuid4(), upload_idempotency_key="another-logical-upload")
    repository = PassportSubmissionRepository(db_session)

    saved, created = await repository.save_idempotent(first)
    assert saved is first and created
    replay, created = await repository.save_idempotent(duplicate)
    assert not created and replay.id == first.id and replay.client_name == first.client_name
    assert (await repository.save_idempotent(independent)) == (independent, True)
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 3
    assert db_session.in_transaction()
