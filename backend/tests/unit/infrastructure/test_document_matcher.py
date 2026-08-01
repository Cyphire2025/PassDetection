from __future__ import annotations

import uuid
from io import BytesIO
from types import SimpleNamespace

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject

from app.infrastructure.documents import document_matcher as document_matcher_module
from app.infrastructure.documents.document_matcher import (
    ClassifiedDocument,
    DocumentMatcher,
    PassengerIdentifier,
)


def _passenger(
    *,
    name: str,
    passport_number: str,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    staff_metadata: dict[str, object] | None = None,
    confirmed_fields: dict[str, object] | None = None,
    custom_answers: list[dict[str, object]] | None = None,
    custom_detail_answers: list[dict[str, object]] | None = None,
) -> SimpleNamespace:
    fields = {
        "given_names": name.split()[0],
        "surname": " ".join(name.split()[1:]),
        "passport_number": passport_number,
        **(confirmed_fields or {}),
    }
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=group_id,
        client_name=name,
        confirmed_fields=fields,
        extracted_fields={},
        staff_metadata=staff_metadata or {},
        custom_answers=custom_answers or [],
        custom_detail_answers=custom_detail_answers or [],
    )


def _document(*, filename: str, text: str = "") -> ClassifiedDocument:
    return ClassifiedDocument(
        original_filename=filename,
        detected_type="visa",
        accepted=True,
        reason="Accepted",
        text=text,
        extracted_name=None,
        extracted_passport_number=None,
        extracted_reference=None,
    )


def _pdf_reader(mutator=None) -> PdfReader:
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    if mutator is not None:
        mutator(writer)
    stream = BytesIO()
    writer.write(stream)
    stream.seek(0)
    return PdfReader(stream)


def test_normal_static_pdf_has_no_active_features() -> None:
    assert DocumentMatcher()._has_active_pdf_features(_pdf_reader()) is False


def test_pdf_javascript_name_tree_is_rejected() -> None:
    assert (
        DocumentMatcher()._has_active_pdf_features(
            _pdf_reader(lambda writer: writer.add_js("app.alert('blocked')"))
        )
        is True
    )


def test_pdf_embedded_attachment_is_rejected() -> None:
    assert (
        DocumentMatcher()._has_active_pdf_features(
            _pdf_reader(lambda writer: writer.add_attachment("payload.txt", b"blocked"))
        )
        is True
    )


def test_pdf_launch_open_action_is_rejected() -> None:
    def add_launch(writer: PdfWriter) -> None:
        writer.root_object[NameObject("/OpenAction")] = DictionaryObject(
            {
                NameObject("/S"): NameObject("/Launch"),
                NameObject("/F"): TextStringObject("blocked.exe"),
            }
        )

    assert DocumentMatcher()._has_active_pdf_features(_pdf_reader(add_launch)) is True


def test_pdf_xfa_form_is_rejected() -> None:
    def add_xfa(writer: PdfWriter) -> None:
        writer.root_object[NameObject("/AcroForm")] = DictionaryObject(
            {NameObject("/XFA"): TextStringObject("blocked")}
        )

    assert DocumentMatcher()._has_active_pdf_features(_pdf_reader(add_xfa)) is True


def test_lightweight_passenger_projection_does_not_require_distribution_metadata() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=group_id,
        client_name="Asha Mehta",
        confirmed_fields={
            "given_names": "Asha",
            "surname": "Mehta",
            "passport_number": "P1234567",
        },
        extracted_fields=None,
    )

    matcher = DocumentMatcher()
    index = matcher.build_index([passenger], agency_id=agency_id, group_id=group_id)
    result = matcher.match(
        _document(filename="ticket.pdf", text="Passport number P1234567"),
        [passenger],
        index=index,
    )

    assert result.passenger_id == passenger.id
    assert result.status == "matched"


def test_payment_confirmation_is_not_classified_as_a_visa() -> None:
    text = """
    PAYMENT CONFIRMATION
    Transaction ID: 98054064033550336
    Fee Type: e-Visa Application Fee
    Fee/Charge Payment
    Customer name: POOJARI RAGHAV NARAYAN
    Tax ID/ID/Passport No.: Z4538350
    Payment details:
    e-Visa application fee
    Payment service fee
    Total amount: 678,759
    Payment method: Online payment
    """

    assert DocumentMatcher()._detect_type(text) == "unknown"


def test_evisa_application_status_without_visa_fields_requires_review() -> None:
    text = """
    Your e-Visa application has been received.
    Application number: ABC123456
    Please retain this confirmation for your records.
    """

    assert DocumentMatcher()._detect_type(text) == "unknown"


def test_value_bearing_visa_grant_can_include_application_status() -> None:
    text = """
    APPLICATION STATUS: GRANTED
    ELECTRONIC VISA GRANT NOTICE
    Grant number: GR12345678
    Valid from: 29 July 2026
    Valid until: 29 August 2026
    """

    assert DocumentMatcher()._detect_type(text) == "visa"


def test_actual_visa_with_document_fields_is_classified_as_visa() -> None:
    text = """
    ELECTRONIC VISA
    Visa number: EV12345678
    Visa type: Tourist
    Number of entries: Multiple entries
    Valid from: 29 July 2026
    Valid until: 29 August 2026
    Duration of stay: 30 days
    Passport number: Z4538350
    """

    assert DocumentMatcher()._detect_type(text) == "visa"


def test_blank_visa_application_form_is_not_classified_as_visa() -> None:
    text = """
    VISA APPLICATION FORM
    Applicant name:
    Visa number:
    Visa type:
    Date of issue:
    Date of expiry:
    Number of entries:
    """

    assert DocumentMatcher()._detect_type(text) == "unknown"


def test_flight_ticket_classification_still_takes_priority() -> None:
    text = """
    E-TICKET ITINERARY
    Booking reference: ABC123
    Flight summary
    Departure: Kochi
    Arrival: Ho Chi Minh City
    """

    assert DocumentMatcher()._detect_type(text) == "flight_ticket"


def test_travel_insurance_claim_invoice_is_not_a_flight_ticket() -> None:
    text = """
    TRAVEL INSURANCE CLAIM INVOICE
    Claim form
    Ticket number:
    Flight number:
    Departure:
    Arrival:
    Total amount: 15000
    """

    assert DocumentMatcher()._detect_type(text) == "unknown"


def test_blank_adjacent_ticket_labels_do_not_supply_each_others_values() -> None:
    text = """
    E-TICKET ITINERARY
    Booking reference:
    Flight number:
    Departure:
    Arrival:
    """

    assert DocumentMatcher()._detect_type(text) == "unknown"


def test_structured_airline_ticket_can_include_tax_invoice() -> None:
    text = """
    E-TICKET ITINERARY RECEIPT / TAX INVOICE
    Booking reference: ABC123
    Departure: Kochi
    Arrival: Singapore
    Passenger: ASHA MEHTA
    """

    assert DocumentMatcher()._detect_type(text) == "flight_ticket"


def test_amadeus_travel_summary_with_value_bearing_fields_is_a_ticket() -> None:
    text = """
    TRAVEL SUMMARY
    BOOKING REF: 84XTUV
    FLIGHT TG 329 - AIRLINE NAME WED 15 JULY 2026
    DEPARTURE: BANGKOK (BKK) 15 JUL 21:50
    ARRIVAL: HYDERABAD (HYD) 15 JUL 23:50
    RESERVATION CONFIRMED, ECONOMY
    FLIGHT TICKET(S)
    TICKET: TG/ETKT 217 4846912517 FOR SAMPLE/TRAVELLER MR
    """

    assert DocumentMatcher()._detect_type(text) == "flight_ticket"


def test_airline_itinerary_with_pnr_sector_and_flight_is_a_ticket() -> None:
    text = """
    PNR / Booking Ref A9LUXJ Confirmed Payment status Complete
    Passenger Information MR SAMPLE TRAVELLER Adult
    Sector Seat Add-ons DEL-BKK
    Departing Delhi DEL - International Airport 15:45, 11 Jul 2026
    Bangkok BKK - International Airport 21:45, 11 Jul 2026
    6E 1053 . A321
    Itinerary
    """

    assert DocumentMatcher()._detect_type(text) == "flight_ticket"


def test_digital_arrival_card_is_never_classified_as_visa_or_ticket() -> None:
    text = """
    Thailand Digital Arrival Card
    Please note that this Digital Arrival Card is not a visa.
    Passport No.: B9451896
    Flight No./Vehicle No.: 6E 1053
    Date of Arrival: 11 July 2026
    Visa No.: EV12345678
    """

    assert DocumentMatcher()._detect_type(text) == "unknown"


def test_filename_words_alone_cannot_classify_unrelated_pdf(monkeypatch) -> None:
    matcher = DocumentMatcher()
    monkeypatch.setattr(
        matcher,
        "_pdf_text",
        lambda _content: "Quarterly financial report and internal meeting notes",
    )

    visa = matcher.classify(filename="visa.pdf", content=b"%PDF-1.7", expected_type="other")
    ticket = matcher.classify(
        filename="flight-ticket.pdf",
        content=b"%PDF-1.7",
        expected_type="other",
    )

    assert visa.detected_type == "unknown"
    assert ticket.detected_type == "unknown"


def test_generic_travel_mention_is_not_a_flight_ticket() -> None:
    text = """
    Team meeting agenda
    Discuss the upcoming flight, departure time, arrival plan, and airline policy.
    """

    assert DocumentMatcher()._detect_type(text) == "unknown"


def test_filename_passport_match_precedes_conflicting_pdf_text() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    first = _passenger(
        name="Asha Mehta",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
    )
    second = _passenger(
        name="Ravi Sharma",
        passport_number="R7654321",
        agency_id=agency_id,
        group_id=group_id,
    )
    matcher = DocumentMatcher()
    index = matcher.build_index([first, second], agency_id=agency_id, group_id=group_id)

    matches = matcher.match_all(
        _document(filename="P1234567.pdf", text="Passenger name: Ravi Sharma R7654321"),
        [first, second],
        index=index,
    )

    assert [(match.passenger_id, match.status) for match in matches] == [(first.id, "matched")]
    assert matches[0].reason.startswith("Filename Passport number")


def test_contradictory_filename_evidence_is_rejected_as_ambiguous() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    first = _passenger(
        name="Asha Mehta",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
    )
    second = _passenger(
        name="Ravi Sharma",
        passport_number="R7654321",
        agency_id=agency_id,
        group_id=group_id,
    )
    matcher = DocumentMatcher()
    index = matcher.build_index([first, second], agency_id=agency_id, group_id=group_id)

    matches = matcher.match_all(
        _document(filename="P1234567_Ravi_Sharma.pdf"),
        [first, second],
        index=index,
    )

    assert matches[0].passenger_id is None
    assert matches[0].status == "needs_review"
    assert "contradictory" in matches[0].reason


def test_duplicate_staff_code_does_not_auto_assign() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passengers = [
        _passenger(
            name=name,
            passport_number=passport,
            agency_id=agency_id,
            group_id=group_id,
            staff_metadata={"staff_code": "1001"},
        )
        for name, passport in (("Asha Mehta", "P1234567"), ("Ravi Sharma", "R7654321"))
    ]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)

    matches = matcher.match_all(_document(filename="1001.pdf"), passengers, index=index)

    assert matches[0].passenger_id is None
    assert matches[0].status == "needs_review"
    assert "ambiguous" in matches[0].reason


def test_unique_and_ambiguous_filename_identifiers_fail_closed_together() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    unique = _passenger(
        name="Asha Mehta",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
        staff_metadata={"staff_code": "111"},
    )
    shared = [
        _passenger(
            name=name,
            passport_number=passport,
            agency_id=agency_id,
            group_id=group_id,
            staff_metadata={"staff_code": "222"},
        )
        for name, passport in (("Ravi Shah", "R7654321"), ("Maya Singh", "M1122334"))
    ]
    passengers = [unique, *shared]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)

    matches = matcher.match_all(
        _document(filename="111_222.pdf"),
        passengers,
        index=index,
    )

    assert matches[0].passenger_id is None
    assert matches[0].status == "needs_review"
    assert "ambiguous" in matches[0].reason


def test_multiple_unique_filename_identifiers_can_match_combined_document() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passengers = [
        _passenger(
            name=name,
            passport_number=passport,
            agency_id=agency_id,
            group_id=group_id,
            staff_metadata={"staff_code": code},
        )
        for name, passport, code in (
            ("Asha Mehta", "P1234567", "111"),
            ("Ravi Shah", "R7654321", "333"),
        )
    ]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)

    matches = matcher.match_all(
        _document(filename="111_333.pdf"),
        passengers,
        index=index,
    )

    assert {match.passenger_id for match in matches} == {passenger.id for passenger in passengers}
    assert {match.status for match in matches} == {"matched"}


def test_single_passport_and_different_single_name_require_review() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    first = _passenger(
        name="Asha Mehta",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
    )
    second = _passenger(
        name="Ravi Shah",
        passport_number="R7654321",
        agency_id=agency_id,
        group_id=group_id,
    )
    passengers = [first, second]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)

    matches = matcher.match_all(
        _document(filename="visa.pdf", text="Passport number P1234567 Name: Ravi Shah"),
        passengers,
        index=index,
    )

    assert matches[0].passenger_id is None
    assert matches[0].status == "needs_review"
    assert "different passengers" in matches[0].reason


def test_single_passport_and_different_labeled_staff_code_require_review() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    first = _passenger(
        name="Asha Mehta",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
    )
    second = _passenger(
        name="Ravi Shah",
        passport_number="R7654321",
        agency_id=agency_id,
        group_id=group_id,
        staff_metadata={"staff_code": "222"},
    )
    passengers = [first, second]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)

    matches = matcher.match_all(
        _document(
            filename="visa.pdf",
            text="Passport number P1234567 Staff code: 222",
        ),
        passengers,
        index=index,
    )

    assert matches[0].passenger_id is None
    assert matches[0].status == "needs_review"


def test_multiple_unique_content_passports_match_combined_document() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passengers = [
        _passenger(
            name=name,
            passport_number=passport,
            agency_id=agency_id,
            group_id=group_id,
        )
        for name, passport in (
            ("Asha Mehta", "P1234567"),
            ("Ravi Shah", "R7654321"),
        )
    ]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)

    matches = matcher.match_all(
        _document(
            filename="combined.pdf",
            text=("Passenger Asha Mehta Passport P1234567 Passenger Ravi Shah Passport R7654321"),
        ),
        passengers,
        index=index,
    )

    assert {match.passenger_id for match in matches} == {passenger.id for passenger in passengers}
    assert {match.status for match in matches} == {"matched"}


def test_combined_passports_with_conflicting_third_name_require_review() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    first = _passenger(
        name="Asha Mehta",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
    )
    second = _passenger(
        name="Ravi Shah",
        passport_number="R7654321",
        agency_id=agency_id,
        group_id=group_id,
    )
    conflicting = _passenger(
        name="Neha Kapoor",
        passport_number="N2468135",
        agency_id=agency_id,
        group_id=group_id,
    )
    passengers = [first, second, conflicting]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)

    matches = matcher.match_all(
        _document(
            filename="combined.pdf",
            text=("Passport P1234567 Passport R7654321 Passenger name: Neha Kapoor"),
        ),
        passengers,
        index=index,
    )

    assert len(matches) == 1
    assert matches[0].passenger_id is None
    assert matches[0].status == "needs_review"
    assert "different passengers" in matches[0].reason


def test_lower_priority_name_set_cannot_expand_combined_passport_set() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    first = _passenger(
        name="Asha Mehta",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
    )
    second = _passenger(
        name="Ravi Shah",
        passport_number="R7654321",
        agency_id=agency_id,
        group_id=group_id,
    )
    extra = _passenger(
        name="Neha Kapoor",
        passport_number="N2468135",
        agency_id=agency_id,
        group_id=group_id,
    )
    passengers = [first, second, extra]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)

    matches = matcher.match_all(
        _document(
            filename="combined.pdf",
            text=(
                "Passport P1234567 Passport R7654321. "
                "Passengers Asha Mehta, Ravi Shah, Neha Kapoor."
            ),
        ),
        passengers,
        index=index,
    )

    assert len(matches) == 1
    assert matches[0].passenger_id is None
    assert matches[0].status == "needs_review"


def test_group_and_custom_agent_codes_are_indexed_with_clear_evidence() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    agent = _passenger(
        name="Asha Mehta",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
        confirmed_fields={
            "agent_employee_type": "agent",
            "agent_employee_code": "00123",
        },
        custom_detail_answers=[{"label": "Traveller reference number", "value": "7788"}],
    )
    matcher = DocumentMatcher()
    index = matcher.build_index([agent], agency_id=agency_id, group_id=group_id)

    prefixed = matcher.match_all(_document(filename="AGT_00123.pdf"), [agent], index=index)
    custom = matcher.match_all(_document(filename="7788.pdf"), [agent], index=index)

    assert prefixed[0].passenger_id == agent.id
    assert "agent or employee code" in prefixed[0].reason
    assert custom[0].passenger_id == agent.id
    assert "stored identifier" in custom[0].reason


def test_supplemental_identifier_is_scope_checked_and_unique() -> None:
    agency_id = uuid.uuid4()
    other_agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = _passenger(
        name="Asha Mehta",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
    )
    matcher = DocumentMatcher()
    foreign = PassengerIdentifier(
        passenger_id=passenger.id,
        agency_id=other_agency_id,
        group_id=group_id,
        kind="agent code",
        value="4455",
        source="linked WhatsApp Excel",
    )
    scoped = PassengerIdentifier(
        passenger_id=passenger.id,
        agency_id=agency_id,
        group_id=group_id,
        kind="agent code",
        value="8899",
        source="linked WhatsApp Excel",
    )
    index = matcher.build_index(
        [passenger],
        agency_id=agency_id,
        group_id=group_id,
        supplemental_identifiers=(foreign, scoped),
    )

    foreign_match = matcher.match_all(
        _document(filename="4455.pdf"),
        [passenger],
        index=index,
    )
    scoped_match = matcher.match_all(
        _document(filename="8899.pdf"),
        [passenger],
        index=index,
    )

    assert foreign_match[0].passenger_id is None
    assert scoped_match[0].passenger_id == passenger.id
    assert "linked WhatsApp Excel" in scoped_match[0].reason


def test_infrastructure_ids_are_not_passenger_identifiers() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = _passenger(
        name="Asha Mehta",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
        staff_metadata={"submission_id": "556677", "agency_id": "998877"},
    )
    matcher = DocumentMatcher()
    index = matcher.build_index([passenger], agency_id=agency_id, group_id=group_id)

    assert (
        matcher.match_all(_document(filename="556677.pdf"), [passenger], index=index)[
            0
        ].passenger_id
        is None
    )
    assert (
        matcher.match_all(_document(filename="998877.pdf"), [passenger], index=index)[
            0
        ].passenger_id
        is None
    )


def test_supplemental_identifier_caps_are_deterministic_and_direct_data_wins(
    monkeypatch,
) -> None:
    monkeypatch.setattr(document_matcher_module, "MAX_PASSENGER_IDENTIFIERS", 2)
    monkeypatch.setattr(
        document_matcher_module,
        "MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER",
        2,
    )
    monkeypatch.setattr(
        document_matcher_module,
        "MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST",
        3,
    )
    monkeypatch.setattr(document_matcher_module, "MAX_SUPPLEMENTAL_IDENTIFIER_INPUTS", 10)
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    direct = _passenger(
        name="Asha Mehta",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
        staff_metadata={"staff_code": "1001"},
    )
    first = _passenger(
        name="Ravi Sharma",
        passport_number="R7654321",
        agency_id=agency_id,
        group_id=group_id,
    )
    second = _passenger(
        name="Maya Singh",
        passport_number="M1122334",
        agency_id=agency_id,
        group_id=group_id,
    )

    def supplemental(passenger, value: str) -> PassengerIdentifier:
        return PassengerIdentifier(
            passenger_id=passenger.id,
            agency_id=agency_id,
            group_id=group_id,
            kind="agent code",
            value=value,
            source="linked WhatsApp Excel",
        )

    index = DocumentMatcher().build_index(
        [direct, first, second],
        agency_id=agency_id,
        group_id=group_id,
        supplemental_identifiers=(
            supplemental(direct, "9901"),
            supplemental(first, "8801"),
            supplemental(first, "8802"),
            supplemental(first, "8803"),
            supplemental(second, "7701"),
            supplemental(second, "7702"),
        ),
    )

    assert "1001" in index.identifiers
    assert "9901" not in index.identifiers
    assert "8801" in index.identifiers
    assert "8802" in index.identifiers
    assert "8803" not in index.identifiers
    assert "7701" in index.identifiers
    assert "7702" not in index.identifiers
