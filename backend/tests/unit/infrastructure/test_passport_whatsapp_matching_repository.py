from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.application.use_cases.whatsapp.group_submission_matching import (
    IdentityEvidenceValues,
)
from app.infrastructure.database.models import (
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    _ascii_cluster_tokens,
    _canonical_search_corpus,
    _token_prefilter,
    load_targeted_unresolved_passport_whatsapp_match_context,
)


def test_targeted_prefilter_includes_bare_indian_phone_source_variant() -> None:
    tokens = _ascii_cluster_tokens(IdentityEvidenceValues(phones=frozenset(("+919876543210",))))

    assert tokens is not None
    assert "919876543210" in tokens
    assert "9876543210" in tokens


def test_targeted_prefilter_fails_closed_for_non_ascii_evidence() -> None:
    assert (
        _ascii_cluster_tokens(IdentityEvidenceValues(names=frozenset(("José Passenger",)))) is None
    )


def test_targeted_prefilter_compiles_as_one_bounded_postgresql_regex() -> None:
    corpus = _canonical_search_corpus(
        PassportSubmissionModel.client_name,
        PassportSubmissionModel.client_phone,
        PassportSubmissionModel.confirmed_fields,
    )
    statement = (
        select(PassportSubmissionModel.id)
        .where(_token_prefilter(corpus, ("919876543210", "EMP001")))
        .limit(65)
    )

    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "regexp_replace" in compiled
    assert compiled.count("regexp_replace(") == 1
    assert " ~ " in compiled
    assert "LIMIT" in compiled


def _result(*rows: object) -> SimpleNamespace:
    return SimpleNamespace(all=lambda: list(rows), scalars=lambda: list(rows))


def _submission(
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    phone: str,
    name: str,
    staff_code: str | None = None,
) -> PassportSubmissionModel:
    return PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=group_id,
        client_name=name,
        client_phone=phone,
        updated_at=datetime.now(tz=UTC),
        status="ai_approved",
        confirmed_fields={"staff_code": staff_code} if staff_code else {},
    )


def _compiled_queries(session: SimpleNamespace) -> list[str]:
    # Exercise the real ORM comparators and the PostgreSQL compiler, rather
    # than mocking column methods (which previously hid an invalid .not_in_).
    return [
        str(
            call.args[0].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for call in session.execute.await_args_list
    ]


async def test_targeted_loader_excludes_loaded_submissions_without_a_broadcast() -> None:
    """Even a GC group with no linked broadcast takes the submission NOT IN path."""
    agency_id, group_id = uuid.uuid4(), uuid.uuid4()
    seed = _submission(agency_id, group_id, phone="+919876543210", name="Seed Passenger")
    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=postgresql.dialect()),
        execute=AsyncMock(side_effect=[_result(), _result(seed), _result(), _result()]),
    )

    context = await load_targeted_unresolved_passport_whatsapp_match_context(
        session,  # type: ignore[arg-type]
        group_id=group_id,
        agency_id=agency_id,
        seed_submission_ids=(seed.id,),
        seed_phone_numbers=frozenset(),
    )

    assert context is not None
    assert context.submissions == (seed,)
    assert context.affected_submission_ids == frozenset({seed.id})
    queries = _compiled_queries(session)
    assert len(queries) == 4
    assert "passport_submissions.id NOT IN" in queries[2]
    assert str(seed.id) in queries[2]
    assert str(group_id) in queries[2]
    assert str(agency_id) in queries[2]
    assert "LIMIT 65" in queries[2]


async def test_targeted_loader_excludes_both_existing_entity_sets_across_three_rounds() -> None:
    """Expand phone -> recipient staff code -> passenger -> second recipient."""
    agency_id, group_id, broadcast_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    seed = _submission(agency_id, group_id, phone="+919876543210", name="Seed Passenger")
    second = _submission(
        agency_id,
        group_id,
        phone="+919876543211",
        name="Related Passenger",
        staff_code="STAFF2",
    )
    first_recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        broadcast_group_id=broadcast_id,
        name="Seed Passenger",
        normalized_phone_number="+919876543210",
        imported_fields={"staff_code": "STAFF2"},
        created_at=seed.updated_at,
    )
    second_recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        broadcast_group_id=broadcast_id,
        name="Related Passenger",
        normalized_phone_number="+919876543211",
        imported_fields={},
        created_at=seed.updated_at,
    )
    session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=postgresql.dialect()),
        execute=AsyncMock(
            side_effect=[
                _result((broadcast_id, "Synthetic legacy roster", None)),
                _result(seed),
                _result(first_recipient),
                _result(second),  # First expansion.
                _result(second_recipient),
                _result(),  # Second expansion.
                _result(),
                _result(),  # Fixed-point proof: nothing more is connected.
                _result(),  # No active manual resolutions.
            ]
        ),
    )

    context = await load_targeted_unresolved_passport_whatsapp_match_context(
        session,  # type: ignore[arg-type]
        group_id=group_id,
        agency_id=agency_id,
        seed_submission_ids=(seed.id,),
        seed_phone_numbers=frozenset(),
    )

    assert context is not None
    assert {item.id for item in context.submissions} == {seed.id, second.id}
    assert {item.id for item in context.recipients} == {first_recipient.id, second_recipient.id}
    assert context.affected_submission_ids == frozenset({seed.id, second.id})
    assert context.affected_phone_numbers == frozenset({"+919876543210", "+919876543211"})
    queries = _compiled_queries(session)
    assert len(queries) == 9
    assert "whatsapp_broadcast_recipients.id NOT IN" not in queries[2]
    for index, expected_ids in (
        (4, (first_recipient.id,)),
        (6, (first_recipient.id, second_recipient.id)),
    ):
        assert "whatsapp_broadcast_recipients.id NOT IN" in queries[index]
        assert all(str(item_id) in queries[index] for item_id in expected_ids)
        assert str(agency_id) in queries[index] and str(broadcast_id) in queries[index]
        assert "LIMIT 65" in queries[index]
    for index, expected_ids in (
        (3, (seed.id,)),
        (5, (seed.id, second.id)),
        (7, (seed.id, second.id)),
    ):
        assert "passport_submissions.id NOT IN" in queries[index]
        assert all(str(item_id) in queries[index] for item_id in expected_ids)
        assert str(group_id) in queries[index] and str(agency_id) in queries[index]
        assert "LIMIT 65" in queries[index]
