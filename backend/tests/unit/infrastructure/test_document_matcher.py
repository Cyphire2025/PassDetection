from __future__ import annotations

from app.infrastructure.documents.document_matcher import DocumentMatcher


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


def test_flight_ticket_classification_still_takes_priority() -> None:
    text = """
    E-TICKET ITINERARY
    Booking reference: ABC123
    Flight summary
    Departure: Kochi
    Arrival: Ho Chi Minh City
    """

    assert DocumentMatcher()._detect_type(text) == "flight_ticket"
