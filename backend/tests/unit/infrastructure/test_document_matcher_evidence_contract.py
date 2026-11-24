"""Public matcher evidence ordering and subclass contracts survive phase extraction."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from app.infrastructure.documents import document_matcher as public
from app.infrastructure.documents.document_match_resolution import DocumentMatchResolution
from app.infrastructure.documents.document_passenger_index import DocumentPassengerIndex
from app.infrastructure.documents.document_type_detection import DocumentTextClassifier


def _passenger(name: str, passport: str, ordinal: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(int=ordinal),
        agency_id=uuid.UUID(int=100),
        group_id=uuid.UUID(int=200),
        client_name=name,
        extracted_fields={},
        confirmed_fields={"full_name": name, "passport_number": passport},
    )


def _document(**changes) -> public.ClassifiedDocument:
    fields = dict(
        original_filename="combined-booking.pdf",
        detected_type="flight_ticket",
        accepted=True,
        reason="Accepted",
        text="Flight itinerary. Passengers: Asha Mehta, Ravi Shah.",
        extracted_name="Asha Mehta",
        extracted_passport_number=None,
        extracted_reference=None,
    )
    return public.ClassifiedDocument(**(fields | changes))


def test_public_class_keeps_its_actual_bases_and_evaluated_annotations():
    assert public.DocumentMatcher.__bases__ == (
        DocumentTextClassifier,
        DocumentPassengerIndex,
        DocumentMatchResolution,
    )
    assert public.DocumentMatcher.__module__ == public.__name__
    for name in ("match", "match_all", "mark_duplicates"):
        method = getattr(public.DocumentMatcher, name)
        assert method.__module__ == public.__name__
        assert method.__qualname__ == f"DocumentMatcher.{name}"
        assert "return" in get_type_hints(method)


def test_single_match_dispatches_the_actual_subclass_override_with_prepared_index():
    expected = public.MatchResult(uuid.UUID(int=1), 0.98, "matched", "Custom evidence")
    calls = []

    class SpecializedMatcher(public.DocumentMatcher):
        def match_all(self, document, passengers, *, index=None):
            calls.append((document, passengers, index))
            return [expected]

    matcher = SpecializedMatcher()
    passengers = [_passenger("Asha Mehta", "P1234567", 1)]
    document = _document()
    index = matcher.build_index(passengers)

    assert matcher.match(document, passengers, index=index) is expected
    assert calls == [(document, passengers, index)]


def test_combined_evidence_keeps_hook_order_global_policy_and_work_counts(monkeypatch):
    events = []
    tokenizations = []
    real_approval = public.has_manual_document_type_approval
    real_classification_type = public.classification_document_type

    def approval(reason):
        events.append("manual approval")
        return real_approval(reason)

    def classification_type(value):
        events.append("manual lane")
        return real_classification_type(value)

    monkeypatch.setattr(public, "has_manual_document_type_approval", approval)
    monkeypatch.setattr(public, "classification_document_type", classification_type)

    class ObservedMatcher(public.DocumentMatcher):
        def _name_words(self, value):
            tokenizations.append(value)
            return super()._name_words(value)

        def _filename_identifier_values(self, value):
            events.append("filename identifiers")
            return super()._filename_identifier_values(value)

        def _resolve_uuid_values(self, values, owners, **options):
            events.append(options["reason"])
            return super()._resolve_uuid_values(values, owners, **options)

        def _resolve_name_windows(self, words, index, **options):
            events.append(options["reason"])
            return super()._resolve_name_windows(words, index, **options)

        def _resolve_identifier_values(self, values, owners, **options):
            events.append(options["prefix"] + " identifiers")
            return super()._resolve_identifier_values(values, owners, **options)

        def _content_passport_values(self, document):
            events.append("content passports")
            return super()._content_passport_values(document)

        def _resolve_ticket_manifest_partial_names(self, text, index):
            events.append("ticket manifest")
            return super()._resolve_ticket_manifest_partial_names(text, index)

        def _content_labeled_identifier_values(self, text):
            events.append("labeled identifiers")
            return super()._content_labeled_identifier_values(text)

    matcher = ObservedMatcher()
    passengers = [
        _passenger("Asha Mehta", "P1234567", 1),
        _passenger("Ravi Shah", "R7654321", 2),
    ]
    document = _document(
        detected_type="unknown",
        reason=public.MANUAL_DOCUMENT_TYPE_APPROVAL_PREFIX + "flight_ticket_domestic",
    )
    index = matcher.build_index(passengers)
    events.clear()
    tokenizations.clear()

    matches = matcher.match_all(document, passengers, index=index)

    assert [(match.passenger_id, match.status) for match in matches] == [
        (passenger.id, "matched") for passenger in passengers
    ]
    assert events == [
        "filename identifiers",
        "Filename Passport number uniquely matched",
        "Filename exact passenger name uniquely matched",
        "Filename identifiers",
        "content passports",
        "PDF text Passport number uniquely matched",
        "PDF text exact passenger name uniquely matched",
        "manual approval",
        "manual lane",
        "ticket manifest",
        "Extracted passenger name uniquely matched",
        "labeled identifiers",
        "PDF text identifiers",
    ]
    assert tokenizations == ["combined-booking", document.text, "Asha Mehta"]


def test_filename_precedence_does_not_visit_pdf_or_manual_policy(monkeypatch):
    matcher = public.DocumentMatcher()
    passengers = [_passenger("Asha Mehta", "P1234567", 1)]
    index = matcher.build_index(passengers)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Filename match must finish before PDF evidence")

    monkeypatch.setattr(matcher, "_content_passport_values", unexpected)
    monkeypatch.setattr(public, "has_manual_document_type_approval", unexpected)
    matches = matcher.match_all(
        _document(original_filename="P1234567.pdf"), passengers, index=index
    )

    assert [(match.passenger_id, match.confidence) for match in matches] == [
        (passengers[0].id, 0.995)
    ]


def test_duplicate_selection_is_stable_and_keeps_unassigned_records():
    first_id, second_id = uuid.UUID(int=1), uuid.UUID(int=2)
    rows = [
        public.MatchResult(first_id, 0.9, "matched", "first"),
        public.MatchResult(first_id, 0.9, "matched", "tie"),
        public.MatchResult(None, 0.0, "needs_review", "unassigned"),
        public.MatchResult(second_id, 0.8, "matched", "lower"),
        public.MatchResult(second_id, 0.95, "matched", "higher"),
    ]
    result = public.DocumentMatcher().mark_duplicates(rows)
    assert [row.status for row in result] == [
        "matched", "duplicate_document", "needs_review", "duplicate_document", "matched"
    ]
    assert result[0] is rows[0]
    assert result[2] is rows[2]
    assert result[4] is rows[4]
    assert [row.passenger_id for row in result] == [row.passenger_id for row in rows]


@pytest.mark.parametrize("evidence", ["passport", "full name", "extracted name", "staff code"])
def test_ambiguous_pdf_evidence_requires_review_before_any_fuzzy_fallback(monkeypatch, evidence):
    first = _passenger("Asha Mehta", "P1234567", 1)
    second = _passenger("Ravi Shah", "R7654321", 2)
    passengers = [first, second]
    text, extracted_name = "Passport P1234567", None
    if evidence == "passport":
        second.confirmed_fields["passport_number"] = "P1234567"
    elif evidence == "full name":
        second.client_name = "Asha Mehta"
        second.confirmed_fields["full_name"] = "Asha Mehta"
        text = "Passengers: Asha Mehta"
    elif evidence == "extracted name":
        passengers.append(_passenger("Ravi Shah", "T1122334", 3))
        text, extracted_name = "Passengers: Asha Mehta", "Ravi Shah"
    else:
        first.staff_metadata = second.staff_metadata = {"staff_code": "222"}
        text = "Staff code: 222"
    matcher = public.DocumentMatcher()
    index = matcher.build_index(passengers)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Ambiguous identity must not reach fuzzy fallback")

    monkeypatch.setattr(matcher, "_bounded_fuzzy_name_match", unexpected)
    result = matcher.match_all(
        _document(text=text, extracted_name=extracted_name), passengers, index=index
    )

    assert result == [
        public.MatchResult(
            None, 0.0, "needs_review", "PDF identity evidence is ambiguous; manual review is required"
        )
    ]


def test_single_match_of_combined_document_keeps_its_review_outcome():
    passengers = [
        _passenger("Asha Mehta", "P1234567", 1),
        _passenger("Ravi Shah", "R7654321", 2),
    ]
    result = public.DocumentMatcher().match(_document(), passengers)
    assert result == public.MatchResult(
        None, 0.96, "needs_review", "Multiple passengers were identified; manual review is required"
    )


def test_single_match_of_empty_subclass_result_keeps_no_candidate_fallback():
    class SpecializedMatcher(public.DocumentMatcher):
        def match_all(self, document, passengers, *, index=None):
            return []

    result = SpecializedMatcher().match(_document(), [_passenger("Asha Mehta", "P1234567", 1)])
    assert result == public.MatchResult(None, 0.0, "needs_review", "No passenger match found")
