"""Export matching keeps ambiguity/Unicode behavior with per-export bounded work."""

import pickle
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import Mock

import pytest

from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientFieldSet,
    SubmissionMatchRow,
)
from app.presentation.api.v1.routes import passport_export_agency_matches as agency
from app.presentation.api.v1.routes import passport_export_support as support


def _row(value, index):
    recipient = uuid.UUID(int=index + 1)
    return SubmissionMatchRow(
        status="not_submitted",
        match_basis=None,
        normalized_phone=None,
        recipient_ids=(recipient,),
        submission_ids=(),
        broadcast_ids=(uuid.UUID(int=99999),),
        broadcast_names=("Synthetic",),
        recipient_names=("Synthetic recipient",),
        submission_names=(),
        updated_at=datetime(2026, 10, 30, tzinfo=UTC),
        recipient_fields=(RecipientFieldSet(recipient_id=recipient, fields={"company": value}),),
    )


def _submission(group, name, index):
    return SimpleNamespace(
        id=uuid.UUID(int=index + 1000),
        group_id=group,
        extracted_fields={},
        confirmed_fields={"agency_dealership_name": name},
        staff_metadata={},
    )


@pytest.mark.parametrize(
    "left,right,expected",
    [
        ("A & B", "a and b", 1.0),
        ("Ｃａｆｅ", "Cafe", 1.0),
        ("cafe\u0301", "CAFÉ", 1.0),
        ("AB", "AC", 0.0),
        (None, "Acme", 0.0),
    ],
)
def test_public_similarity_retains_exact_unicode_and_short_value_rules(left, right, expected):
    assert support._agency_match_similarity(left, right) == expected


def test_ambiguous_agency_is_not_selected_and_cache_cannot_survive_next_export():
    group = uuid.uuid4()
    submission = _submission(group, "A & B", 1)
    first, duplicate = _row("a and b", 1), _row("A & B", 2)
    result = support._export_agency_matches(
        [submission], {group: [first, duplicate]}, "whatsapp:company"
    )
    assert result.rows_by_submission == {} and not result.matched_recipient_ids
    result = support._export_agency_matches([submission], {group: [first]}, "whatsapp:company")
    assert result.rows_by_submission == {submission.id: first}
    submission.confirmed_fields["agency_dealership_name"] = "Completely Different"
    result = support._export_agency_matches([submission], {group: [first]}, "whatsapp:company")
    assert result.rows_by_submission == {} and not result.matched_recipient_ids


def test_repeated_pair_scoring_normalizes_inputs_once_per_export_value(monkeypatch):
    group = uuid.uuid4()
    submissions = [_submission(group, f"Synthetic travel agency {n:04} old", n) for n in range(120)]
    rows = [_row(f"Synthetic travel agency {n:04} new", n) for n in range(80)]
    normalize = Mock(wraps=agency._normalized_agency_match_value)
    monkeypatch.setattr(agency, "_normalized_agency_match_value", normalize)
    support._export_agency_matches(submissions, {group: rows}, "whatsapp:company")
    # Keep the original two normalization passes (including compatibility
    # Unicode behavior), but do not repeat them for every candidate pair.
    assert normalize.call_count <= 2 * (len(submissions) + len(rows))


def test_export_match_context_keeps_legacy_single_identity_pickle_and_type_resolution():
    row = _row("Synthetic", 1)
    value = support._AgencyExportMatches({uuid.UUID(int=1000): row}, frozenset(row.recipient_ids))
    assert type(value) is agency._AgencyExportMatches
    assert type(value).__module__ == support.__name__
    assert pickle.loads(pickle.dumps(value)) == value
    assert set(get_type_hints(type(value))) == {"rows_by_submission", "matched_recipient_ids"}
