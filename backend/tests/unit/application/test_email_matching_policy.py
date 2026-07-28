from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

from app.application.use_cases.email_integrations.matching import (
    GroupForAssociation,
    associate_group,
    associate_passenger,
)
from app.infrastructure.documents.document_matcher import ClassifiedDocument


def _document(
    *,
    text: str,
    passport_number: str | None = None,
    name: str | None = None,
) -> ClassifiedDocument:
    return ClassifiedDocument(
        original_filename="ticket.pdf",
        detected_type="flight_ticket",
        accepted=True,
        reason="Accepted",
        text=text,
        extracted_name=name,
        extracted_passport_number=passport_number,
        extracted_reference=None,
    )


def _passenger(
    *,
    group_id: uuid.UUID,
    name: str,
    passport_number: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        group_id=group_id,
        client_name=name,
        confirmed_fields={
            "given_names": name.split()[0],
            "surname": name.split()[-1],
            "passport_number": passport_number,
        },
        extracted_fields=None,
    )


def test_exact_passport_number_is_a_unique_group_decision() -> None:
    first_group = uuid.uuid4()
    second_group = uuid.uuid4()
    passenger = _passenger(
        group_id=first_group,
        name="Asha Mehta",
        passport_number="P1234567",
    )
    other = _passenger(
        group_id=second_group,
        name="Ravi Shah",
        passport_number="R7654321",
    )

    result = associate_group(
        email_text="Please find the attached ticket.",
        document=_document(text="Passport P1234567", passport_number="P1234567"),
        groups=[],
        passengers=[passenger, other],
    )

    assert result.status == "matched"
    assert result.group_id == first_group
    assert result.confidence == 0.99
    assert result.evidence == ("passport_number_exact",)


def test_group_name_needs_corroboration_before_automation() -> None:
    group_id = uuid.uuid4()
    group = GroupForAssociation(
        id=group_id,
        name="Singapore July Group",
        token="never-present",
        destination="Singapore",
        travel_date=date(2026, 7, 20),
    )
    document = _document(text="Flight itinerary")

    name_only = associate_group(
        email_text="Singapore July Group documents",
        document=document,
        groups=[group],
        passengers=[],
    )
    corroborated = associate_group(
        email_text="Singapore July Group departs Singapore on 20 July 2026",
        document=document,
        groups=[group],
        passengers=[],
    )

    assert name_only.status == "needs_review"
    assert name_only.group_id == group_id
    assert corroborated.status == "matched"
    assert corroborated.group_id == group_id


def test_passenger_name_is_a_proposal_but_not_an_automatic_match() -> None:
    group_id = uuid.uuid4()
    passenger = _passenger(
        group_id=group_id,
        name="Asha Mehta",
        passport_number="P1234567",
    )

    result = associate_passenger(
        document=_document(text="Passenger Asha Mehta", name="Asha Mehta"),
        passengers=[passenger],
    )

    assert result.passenger_id == passenger.id
    assert result.status == "needs_review"
    assert result.evidence == ("passenger_name_candidate",)


def test_passenger_passport_number_can_auto_match() -> None:
    group_id = uuid.uuid4()
    passenger = _passenger(
        group_id=group_id,
        name="Asha Mehta",
        passport_number="P1234567",
    )

    result = associate_passenger(
        document=_document(text="Passport P1234567", passport_number="P1234567"),
        passengers=[passenger],
    )

    assert result.passenger_id == passenger.id
    assert result.status == "matched"
    assert result.confidence == 0.98
