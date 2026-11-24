"""Exact matching falls back whenever the bounded component is not proven complete."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.application.use_cases.whatsapp.group_submission_matching import IdentityEvidenceValues
from app.infrastructure.database.models import (
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories import passport_whatsapp_matching_repository as matching


def _result(*rows):
    return SimpleNamespace(all=lambda: list(rows), scalars=lambda: list(rows))


def _session(*results, dialect=None):
    return SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=dialect or postgresql.dialect()),
        execute=AsyncMock(side_effect=results),
    )


def _submission(agency, group, *, name="Synthetic passenger", phone="+919876543210"):
    return PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=agency,
        group_id=group,
        client_name=name,
        client_phone=phone,
        status="ai_approved",
        updated_at=datetime(2026, 10, 30, tzinfo=UTC),
    )


async def _load(session, agency, group, *seeds, limit=64):
    return await matching.load_targeted_unresolved_passport_whatsapp_match_context(
        session,
        agency_id=agency,
        group_id=group,
        seed_submission_ids=tuple(seeds),
        seed_phone_numbers=frozenset(),
        max_cluster_size=limit,
    )


@pytest.mark.parametrize(
    "stored,expected",
    [
        (None, None),
        ([], ()),
        (["name", "name", "phone_number"], ("name", "phone_number")),
        ("name", ()),
        ([1], ()),
        (["name", None], ()),
        (["Name"], ()),
        (["a" * 65], ()),
    ],
)
def test_stored_policy_distinguishes_legacy_and_fail_closed_explicit_values(stored, expected):
    assert matching.matching_field_keys_from_storage(stored) == expected


def test_token_limits_remain_live_at_original_import_path(monkeypatch):
    evidence = IdentityEvidenceValues(names=frozenset({"Synthetic Passenger"}))
    monkeypatch.setattr(matching, "_TARGETED_MATCH_TOKEN_LIMIT", 0)
    assert matching._ascii_cluster_tokens(evidence) is None
    monkeypatch.setattr(matching, "_TARGETED_MATCH_TOKEN_LIMIT", 256)
    monkeypatch.setattr(matching, "_TARGETED_MATCH_TOKEN_BYTES_LIMIT", 1)
    assert matching._ascii_cluster_tokens(evidence) is None
    assert matching._ascii_cluster_tokens(IdentityEvidenceValues(names=frozenset({"A"}))) is None


@pytest.mark.parametrize(
    "seed_count,dialect,limit",
    [
        (0, postgresql.dialect(), 64),
        (2, postgresql.dialect(), 1),
        (1, sqlite.dialect(), 64),
    ],
)
async def test_invalid_seed_bounds_and_unsupported_dialect_never_query(seed_count, dialect, limit):
    session = _session(dialect=dialect)
    assert (
        await _load(
            session,
            uuid.uuid4(),
            uuid.uuid4(),
            *(uuid.uuid4() for _ in range(seed_count)),
            limit=limit,
        )
        is None
    )
    session.execute.assert_not_awaited()


@pytest.mark.parametrize("policy", [["name"], [], "malformed"])
async def test_explicit_or_corrupt_link_policy_falls_back_before_seed_read(policy):
    agency, group, broadcast = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    session = _session(_result((broadcast, "Synthetic", policy)))
    assert await _load(session, agency, group, uuid.uuid4()) is None
    assert session.execute.await_count == 1


async def test_link_overflow_falls_back_before_seed_read():
    agency, group = uuid.uuid4(), uuid.uuid4()
    session = _session(_result((uuid.uuid4(), "A", None), (uuid.uuid4(), "B", None)))
    assert await _load(session, agency, group, uuid.uuid4(), limit=1) is None
    assert session.execute.await_count == 1


@pytest.mark.parametrize("overflow", ["recipients", "submissions", "total", "resolutions"])
async def test_each_component_bound_falls_back_without_emitting_partial_context(overflow):
    agency, group, broadcast = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    seed = _submission(agency, group)
    linked = _result((broadcast, "Synthetic", None))
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=agency,
        broadcast_group_id=broadcast,
        name=seed.client_name,
        normalized_phone_number=seed.client_phone,
        created_at=seed.updated_at,
    )
    variants = {
        "recipients": [linked, _result(seed), _result(recipient, recipient)],
        "submissions": [_result(), _result(seed), _result(seed, seed)],
        "total": [linked, _result(seed), _result(recipient), _result()],
        "resolutions": [_result(), _result(seed), _result(), _result(object(), object())],
    }
    session = _session(*variants[overflow])
    assert await _load(session, agency, group, seed.id, limit=1) is None
    assert session.execute.await_count == len(variants[overflow])


async def test_round_exhaustion_retains_authoritative_fallback(monkeypatch):
    agency, group, broadcast = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    seed = _submission(agency, group)
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=agency,
        broadcast_group_id=broadcast,
        name=seed.client_name,
        normalized_phone_number=seed.client_phone,
        created_at=seed.updated_at,
    )
    session = _session(
        _result((broadcast, "Synthetic", None)), _result(seed), _result(recipient), _result()
    )
    monkeypatch.setattr(matching, "_TARGETED_MATCH_MAX_ROUNDS", 1)
    assert await _load(session, agency, group, seed.id) is None
    assert session.execute.await_count == 4


async def test_non_ascii_evidence_falls_back_before_graph_queries():
    agency, group = uuid.uuid4(), uuid.uuid4()
    seed = _submission(agency, group, name="José Synthetic")
    session = _session(_result(), _result(seed))
    assert await _load(session, agency, group, seed.id) is None
    assert session.execute.await_count == 2


async def test_false_positive_candidates_are_discarded_and_original_comparator_is_live(monkeypatch):
    agency, group, broadcast = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    seed = _submission(agency, group)
    unrelated = _submission(agency, group, name="Unrelated Other", phone="+919876543299")
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=agency,
        broadcast_group_id=broadcast,
        name="Different Recipient",
        normalized_phone_number="+919876543298",
        created_at=seed.updated_at,
    )
    session = _session(
        _result((broadcast, "Synthetic", None)),
        _result(seed),
        _result(recipient),
        _result(unrelated),
        _result(),
    )
    compare = Mock(wraps=matching.compare_group_submissions)
    monkeypatch.setattr(matching, "compare_group_submissions", compare)
    context = await _load(session, agency, group, seed.id)
    assert context is not None
    assert context.submissions == (seed,) and context.recipients == ()
    compare.assert_called_once()
    assert compare.call_args.args[0] == []
    assert [row.id for row in compare.call_args.args[1]] == [seed.id]
    for call in session.execute.await_args_list:
        sql = str(
            call.args[0].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        assert str(agency) in sql


async def test_active_resolution_exclusion_retains_models_but_removes_comparison_evidence(
    monkeypatch,
):
    agency, group = uuid.uuid4(), uuid.uuid4()
    seed = _submission(agency, group)
    resolution = PassportRosterResolutionModel(
        id=uuid.uuid4(),
        agency_id=agency,
        client_group_id=group,
        submission_id=seed.id,
        excluded_submission_ids=["invalid", str(seed.id)],
        status="active",
    )
    session = _session(_result(), _result(seed), _result(), _result(resolution))
    compare = Mock(wraps=matching.compare_group_submissions)
    monkeypatch.setattr(matching, "compare_group_submissions", compare)
    context = await _load(session, agency, group, seed.id)
    assert context is not None and context.submissions == (seed,)
    assert context.rows == () and context.affected_submission_ids == frozenset({seed.id})
    compare.assert_called_once_with([], [])
