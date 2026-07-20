from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.application.use_cases.passports.submission_view import (
    build_submission_view,
)


def _submission(
    *,
    name: str,
    status: str = "ai_approved",
    confirmed: dict[str, str] | None = None,
    extracted: dict[str, str] | None = None,
    email: str | None = None,
    verification: dict | None = None,
    overall_confidence: float | None = None,
    submission_id: uuid.UUID | None = None,
    updated_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=submission_id or uuid.uuid4(),
        client_name=name,
        client_email=email,
        client_phone=None,
        family_head_name=None,
        family_head_email=None,
        family_head_phone=None,
        departure_city=None,
        confirmed_fields=confirmed or {},
        extracted_fields=extracted or {},
        post_submission_verification=verification,
        overall_confidence=overall_confidence,
        status=status,
        updated_at=updated_at
        or datetime(2026, 7, 20, 12, tzinfo=UTC),
    )


def _passport_fields(
    passport_number: str,
    issuing_country: str,
    *,
    given_names: str = "Asha",
    surname: str = "Kumar",
    birth: str = "1990-01-02",
    nationality: str = "Indian",
    expiry: str = "2030-01-01",
) -> dict[str, str]:
    return {
        "passport_number": passport_number,
        "issuing_country": issuing_country,
        "given_names": given_names,
        "surname": surname,
        "date_of_birth": birth,
        "nationality": nationality,
        "date_of_expiry": expiry,
    }


def test_country_aliases_and_surname_empty_form_one_duplicate_cluster() -> None:
    first = _submission(
        name="Asha",
        confirmed=_passport_fields(
            "P123", "IND", surname="", given_names="Asha"
        ),
        extracted={"surname": "SHOULD NOT OVERRIDE"},
    )
    second = _submission(
        name="Asha",
        confirmed=_passport_fields(
            "P123", "India", surname="", given_names="Asha"
        ),
    )
    view = build_submission_view(
        [first, second],
        submission_filter="duplicates",
        sort_by="name",
        sort_order="asc",
        search=None,
        page=1,
        page_size=50,
    )

    assert view.total == 2
    assert len({item.duplicate_cluster_id for item in view.items}) == 1
    assert view.items[0].duplicate_cluster_id is not None
    assert view.items[0].duplicate_cluster_id.startswith(
        f"dup_{min(first.id, second.id, key=str).hex}"
    )
    assert all(item.duplicate_cluster_size == 2 for item in view.items)


def test_mixed_country_missing_requires_corroboration_and_rejects_conflict() -> None:
    complete = _submission(
        name="Asha",
        confirmed=_passport_fields("P900", "IND"),
    )
    country_missing = _submission(
        name="Asha",
        confirmed=_passport_fields("P900", ""),
    )
    wrong_birth = _submission(
        name="Asha",
        confirmed=_passport_fields("P900", "", birth="1991-01-02"),
    )
    conflicting_country = _submission(
        name="Asha",
        confirmed=_passport_fields("P900", "USA"),
    )
    view = build_submission_view(
        [complete, country_missing, wrong_birth],
        submission_filter="duplicates",
        sort_by="name",
        sort_order="asc",
        search=None,
        page=1,
        page_size=50,
    )

    assert {item.submission.id for item in view.items} == {
        complete.id,
        country_missing.id,
    }
    conflicting_view = build_submission_view(
        [complete, conflicting_country],
        submission_filter="duplicates",
        sort_by="name",
        sort_order="asc",
        search=None,
        page=1,
        page_size=50,
    )
    assert conflicting_view.items == ()


def test_search_returns_whole_cluster_then_status_filter_is_member_truthful() -> None:
    fields = _passport_fields("P777", "IND")
    approved = _submission(
        name="Asha",
        status="ai_approved",
        confirmed=fields,
        email="asha@example.test",
    )
    review = _submission(
        name="Different display name",
        status="needs_review",
        confirmed=fields,
        email="only-hit@example.test",
    )
    searched = build_submission_view(
        [approved, review],
        submission_filter="all",
        sort_by="name",
        sort_order="asc",
        search="only-hit",
        page=1,
        page_size=50,
    )
    approved_only = build_submission_view(
        [approved, review],
        submission_filter="ai_approved",
        sort_by="name",
        sort_order="asc",
        search="only-hit",
        page=1,
        page_size=50,
    )

    assert {item.submission.id for item in searched.items} == {
        approved.id,
        review.id,
    }
    assert [item.submission.id for item in approved_only.items] == [
        approved.id
    ]
    assert approved_only.items[0].duplicate_cluster_size == 2
    assert set(
        approved_only.items[0].duplicate_cluster_member_ids
    ) == {approved.id, review.id}


def test_block_pagination_never_splits_cluster_beyond_first_hundred() -> None:
    singles = [
        _submission(
            name=f"A{index:03d}",
            confirmed=_passport_fields(f"UNIQUE{index}", "IND"),
        )
        for index in range(99)
    ]
    duplicate_fields = _passport_fields("DUP100", "IND")
    duplicate_a = _submission(name="A099", confirmed=duplicate_fields)
    duplicate_b = _submission(name="A099", confirmed=duplicate_fields)
    tail = _submission(
        name="Z999",
        confirmed=_passport_fields("TAIL", "IND"),
    )
    submissions = [*singles, duplicate_a, duplicate_b, tail]

    first_page = build_submission_view(
        submissions,
        submission_filter="all",
        sort_by="name",
        sort_order="asc",
        search=None,
        page=1,
        page_size=100,
    )
    second_page = build_submission_view(
        submissions,
        submission_filter="all",
        sort_by="name",
        sort_order="asc",
        search=None,
        page=2,
        page_size=100,
    )

    first_ids = {item.submission.id for item in first_page.items}
    second_ids = {item.submission.id for item in second_page.items}
    assert first_page.returned_count == 99
    assert {duplicate_a.id, duplicate_b.id}.issubset(second_ids)
    assert first_ids.isdisjoint(second_ids)
    assert first_ids | second_ids == {
        submission.id for submission in submissions
    }


def test_confidence_sort_uses_display_value_and_keeps_null_last_both_ways() -> None:
    low = _submission(
        name="Low",
        verification={"confidence": 0.4, "fields": []},
    )
    high_fallback = _submission(
        name="High",
        overall_confidence=0.9,
    )
    invalid_legacy = _submission(
        name="Invalid",
        verification={
            "confidence": 0.99,
            "fields": [
                {
                    "confidence": 0.99,
                    "observed_value": "",
                    "reason_code": "unreadable",
                }
            ],
        },
        overall_confidence=0.8,
    )
    missing = _submission(name="Missing")
    ascending = build_submission_view(
        [missing, invalid_legacy, high_fallback, low],
        submission_filter="all",
        sort_by="verification_confidence",
        sort_order="asc",
        search=None,
        page=1,
        page_size=50,
    )
    descending = build_submission_view(
        [missing, invalid_legacy, high_fallback, low],
        submission_filter="all",
        sort_by="verification_confidence",
        sort_order="desc",
        search=None,
        page=1,
        page_size=50,
    )

    assert [
        item.verification_confidence for item in ascending.items
    ] == [0.4, 0.8, 0.9, None]
    assert [
        item.verification_confidence for item in descending.items
    ] == [0.9, 0.8, 0.4, None]


def test_expiry_alerts_are_full_group_and_filter_independent_at_boundary() -> None:
    today = date(2026, 1, 31)
    expired = _submission(
        name="Expired",
        confirmed=_passport_fields(
            "EXP", "IND", expiry="2026-01-30"
        ),
    )
    boundary = _submission(
        name="Boundary",
        confirmed=_passport_fields(
            "BOUND", "IND", expiry="2026-07-31"
        ),
    )
    valid = _submission(
        name="Valid",
        confirmed=_passport_fields(
            "VALID", "IND", expiry="2026-08-01"
        ),
    )
    view = build_submission_view(
        [expired, boundary, valid],
        submission_filter="staff_approved",
        sort_by="updated_at",
        sort_order="desc",
        search="does-not-match",
        page=1,
        page_size=1,
        today=today,
    )

    assert view.items == ()
    assert view.group_total == 3
    assert [
        (
            alert.submission_id,
            alert.passport_number,
            alert.status,
        )
        for alert in view.expiry_alerts
    ] == [
        (expired.id, "EXP", "expired"),
        (boundary.id, "BOUND", "near_expiry"),
    ]
