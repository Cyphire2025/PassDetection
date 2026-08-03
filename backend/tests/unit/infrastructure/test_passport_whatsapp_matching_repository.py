from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.application.use_cases.whatsapp.group_submission_matching import (
    IdentityEvidenceValues,
)
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    _ascii_cluster_tokens,
    _canonical_search_corpus,
    _token_prefilter,
)


def test_targeted_prefilter_includes_bare_indian_phone_source_variant() -> None:
    tokens = _ascii_cluster_tokens(
        IdentityEvidenceValues(phones=frozenset(("+919876543210",)))
    )

    assert tokens is not None
    assert "919876543210" in tokens
    assert "9876543210" in tokens


def test_targeted_prefilter_fails_closed_for_non_ascii_evidence() -> None:
    assert (
        _ascii_cluster_tokens(
            IdentityEvidenceValues(names=frozenset(("José Passenger",)))
        )
        is None
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
