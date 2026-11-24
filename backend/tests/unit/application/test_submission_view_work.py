"""Bound repeated key preparation while preserving roster ordering and search results."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.application.use_cases.passports import submission_view as view
from app.application.use_cases.passports import submission_view_fields as fields
from app.application.use_cases.passports import submission_view_ordering as ordering
from tests.unit.application.test_submission_view import _passport_fields, _submission


def rows():
    return [
        _submission(
            name=f"Synthetic {index:04}",
            confirmed=_passport_fields(f"P{index:04}", "Chennai"),
            submission_id=uuid.UUID(int=index + 1),
            overall_confidence=0.9 if index % 2 else None,
        )
        for index in range(512)
    ]


@pytest.mark.parametrize(("search", "expected"), [("missing-synthetic-token", 0), ("---", 512)])
def test_nonblank_search_key_is_normalized_once_for_the_full_roster(monkeypatch, search, expected):
    actual = fields._normalized_tokens
    calls = 0

    def count(value):
        nonlocal calls
        if value == search:
            calls += 1
        return actual(value)

    for owner in (fields, ordering, view):
        monkeypatch.setattr(owner, "_normalized_tokens", count)
    result = view.prepare_submission_view(
        rows(),
        submission_filter="all",
        sort_by="name",
        sort_order="asc",
        search=search,
        page_size=50,
        today=date(2026, 1, 1),
    )
    assert result.total == expected
    assert result.ordered_submission_ids == tuple(uuid.UUID(int=i + 1) for i in range(expected))
    assert calls == 1


@pytest.mark.parametrize("sort_by", ["name", "verification_confidence", "updated_at"])
@pytest.mark.parametrize("order", ["asc", "desc"])
def test_sort_partition_reads_each_key_at_most_once_before_each_sort(monkeypatch, sort_by, order):
    actual = ordering._sort_value
    calls = 0

    def count(entry, key):
        nonlocal calls
        calls += 1
        return actual(entry, key)

    monkeypatch.setattr(ordering, "_sort_value", count)
    submissions = rows()
    result = view.prepare_submission_view(
        submissions,
        submission_filter="all",
        sort_by=sort_by,
        sort_order=order,
        search=None,
        page_size=50,
        today=date(2026, 1, 1),
    )
    expected = list(range(512))
    if sort_by == "verification_confidence":
        expected = [i for i in expected if i % 2] + [i for i in expected if not i % 2]
    elif sort_by == "name" and order == "desc":
        expected.reverse()
    assert result.ordered_submission_ids == tuple(uuid.UUID(int=i + 1) for i in expected)
    assert result.total == result.group_total == 512
    assert all(len(page) <= 50 for page in result.pages)
    populated = 256 if sort_by == "verification_confidence" else 512
    assert calls <= 2 * (512 + populated)
