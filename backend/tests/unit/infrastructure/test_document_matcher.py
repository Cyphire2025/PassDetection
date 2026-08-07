from __future__ import annotations

import sys
import uuid
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, TextStringObject

from app.infrastructure.documents import document_matcher as document_matcher_module
from app.infrastructure.documents.document_matcher import (
    PDF_OCR_RETRY_REASON,
    ClassifiedDocument,
    DocumentMatcher,
    DocumentOcrUnavailableError,
    DocumentParserUnavailableError,
    PassengerIdentifier,
    UnsupportedDocumentBatchFormatError,
    classify_documents_bounded,
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


VIETNAM_EVISA_LAYOUTS = (
    (
        "label-before-same-line",
        """
        SOCIALIST REPUBLIC OF VIETNAM
        VIETNAM ELECTRONIC VISA
        Issuing authority: Vietnam Immigration Department
        Visa number: EVN240001
        Full name: ASHA MEHTA
        Passport number: P1234567
        Valid from: 01 August 2026
        Valid until: 30 August 2026
        Number of entries: Multiple
        """,
        "Asha Mehta",
        "P1234567",
        "EVN240001",
    ),
    (
        "label-before-nearby-line",
        """
        E-VISA
        Issuing authority
        Vietnam Immigration Department
        Document reference
        EVN240002
        Full name
        RAVI SHARMA
        Passport no.
        R7654321
        Valid from
        02/08/2026
        Valid until
        31/08/2026
        Entries
        Single
        """,
        "Ravi Sharma",
        "R7654321",
        "EVN240002",
    ),
    (
        "value-before-english-bilingual-label",
        """
        THI THUC DIEN TU / VIETNAM E-VISA
        CUC QUAN LY XUAT NHAP CANH / VIETNAM IMMIGRATION DEPARTMENT
        EVN240003
        Visa number / So thi thuc
        MAYA SINGH
        Full name / Ho va ten
        M1122334
        Passport number / So ho chieu
        03-08-2026
        Valid from / Co gia tri tu
        01-09-2026
        Valid until / Den
        Multiple
        Number of entries / So lan nhap canh
        """,
        "Maya Singh",
        "M1122334",
        "EVN240003",
    ),
    (
        "unicode-bilingual-labels-and-name",
        """
        THỊ THỰC ĐIỆN TỬ VIỆT NAM / VIETNAM E-VISA
        Cục Quản lý Xuất nhập cảnh / Vietnam Immigration Department
        Số thị thực / Visa reference: EVN240004
        Họ và tên / Full name: NGUYỄN THỊ ÁNH
        Số hộ chiếu / Passport number: B2233445
        Có giá trị từ / Valid from: 04/08/2026
        Đến / Valid until: 02/09/2026
        Số lần nhập cảnh / Number of entries: Multiple
        """,
        "Nguyễn Thị Ánh",
        "B2233445",
        "EVN240004",
    ),
    (
        "mixed-order-nearby-values",
        """
        ELECTRONIC VISA - VIET NAM
        Vietnam Immigration Authority
        PRIYA IYER
        Full name / Ho va ten
        Passport number / So ho chieu
        N3344556
        Date of expiry / Ngay het han
        05 September 2026
        EVN240005
        Visa reference / Ma thi thuc
        Two
        Entries / So lan nhap canh
        Date of issue / Ngay cap
        06 August 2026
        """,
        "Priya Iyer",
        "N3344556",
        "EVN240005",
    ),
)


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


@pytest.mark.parametrize(
    ("text", "expected_name", "expected_passport", "expected_reference"),
    [layout[1:] for layout in VIETNAM_EVISA_LAYOUTS],
    ids=[layout[0] for layout in VIETNAM_EVISA_LAYOUTS],
)
def test_varied_vietnam_evisa_layouts_extract_the_same_verified_facts(
    monkeypatch,
    text: str,
    expected_name: str,
    expected_passport: str,
    expected_reference: str,
) -> None:
    matcher = DocumentMatcher()
    monkeypatch.setattr(matcher, "_pdf_text", lambda _content: text)

    result = matcher.classify(
        filename="source.pdf",
        content=b"%PDF-1.7 synthetic",
        expected_type="visa",
    )

    assert result.detected_type == "visa"
    assert result.accepted is True
    assert result.extracted_name == expected_name
    assert result.extracted_passport_number == expected_passport
    assert result.extracted_reference == expected_reference


def test_identity_facts_are_extracted_independently_of_document_classification(
    monkeypatch,
) -> None:
    text = """
    INTERNAL PARTICIPANT RECORD
    Full name: LEENA DAS
    Passport number: L4455667
    Document reference: DOC901122
    Meeting date: 07 August 2026
    """
    matcher = DocumentMatcher()
    monkeypatch.setattr(matcher, "_pdf_text", lambda _content: text)

    result = matcher.classify(
        filename="record.pdf",
        content=b"%PDF-1.7 synthetic",
        expected_type="other",
    )

    assert result.detected_type == "unknown"
    assert result.extracted_name == "Leena Das"
    assert result.extracted_passport_number == "L4455667"
    assert result.extracted_reference == "DOC901122"


@pytest.mark.parametrize("reference_label", ("Visa number", "N0"))
def test_visa_reference_never_borrows_an_earlier_passport_no(
    monkeypatch,
    reference_label: str,
) -> None:
    text = f"""
    VIETNAM ELECTRONIC VISA
    Vietnam Immigration Department
    Passport No: P1234567
    {reference_label}: EVN240099
    Valid from: 01 August 2026
    Number of entries: Multiple
    """
    matcher = DocumentMatcher()
    monkeypatch.setattr(matcher, "_pdf_text", lambda _content: text)

    result = matcher.classify(
        filename="visa.pdf",
        content=b"%PDF-1.7 synthetic",
        expected_type="visa",
    )

    assert result.extracted_passport_number == "P1234567"
    assert result.extracted_reference == "EVN240099"


def test_ticket_passenger_name_is_not_replaced_by_airline_name(monkeypatch) -> None:
    text = """
    E-TICKET ITINERARY
    Booking reference: ABC123
    AIRLINE NAME: GLOBAL AIRWAYS
    Departure: Delhi
    Arrival: Hanoi
    Passenger name: ASHA MEHTA
    """
    matcher = DocumentMatcher()
    monkeypatch.setattr(matcher, "_pdf_text", lambda _content: text)

    result = matcher.classify(
        filename="ticket.pdf",
        content=b"%PDF-1.7 synthetic",
        expected_type="flight_ticket",
    )

    assert result.detected_type == "flight_ticket"
    assert result.extracted_name == "Asha Mehta"


def test_rename_and_distribution_expected_types_return_identical_detected_facts(
    monkeypatch,
) -> None:
    text = VIETNAM_EVISA_LAYOUTS[0][1]
    matcher = DocumentMatcher()
    monkeypatch.setattr(matcher, "_pdf_text", lambda _content: text)

    rename_result = matcher.classify(
        filename="visa.pdf",
        content=b"%PDF-1.7 synthetic",
        expected_type="other",
    )
    distribution_result = matcher.classify(
        filename="visa.pdf",
        content=b"%PDF-1.7 synthetic",
        expected_type="visa",
    )

    assert (
        rename_result.detected_type,
        rename_result.extracted_name,
        rename_result.extracted_passport_number,
        rename_result.extracted_reference,
    ) == (
        distribution_result.detected_type,
        distribution_result.extracted_name,
        distribution_result.extracted_passport_number,
        distribution_result.extracted_reference,
    )
    assert rename_result.accepted is True
    assert distribution_result.accepted is True


def test_common_unknown_batch_raises_once_only_when_a_shared_format_is_verifiable(
    monkeypatch,
) -> None:
    first_content = b"%PDF-1.7 unsupported-one"
    second_content = b"%PDF-1.7 unsupported-two"
    common_text = {
        first_content: """
            REGIONAL TRAVEL CLEARANCE RECORD
            Full name: FIRST PERSON
            Passport number: F1000001
            Document reference: RC100001
        """,
        second_content: """
            REGIONAL TRAVEL CLEARANCE RECORD
            Full name: SECOND PERSON
            Passport number: S2000002
            Document reference: RC100002
        """,
    }
    matcher = DocumentMatcher()
    monkeypatch.setattr(matcher, "_pdf_text", common_text.__getitem__)
    jobs = [
        ("first.pdf", first_content, "other"),
        ("second.pdf", second_content, "other"),
    ]

    ordinary_results = classify_documents_bounded(
        matcher,
        jobs,
        isolate_pdf_parsing=False,
    )
    assert [item.detected_type for item in ordinary_results] == ["unknown", "unknown"]

    with pytest.raises(UnsupportedDocumentBatchFormatError):
        classify_documents_bounded(
            matcher,
            jobs,
            isolate_pdf_parsing=False,
            reject_common_unsupported_format=True,
        )

    image_only_matcher = DocumentMatcher()
    monkeypatch.setattr(image_only_matcher, "_pdf_text", lambda _content: "")
    image_only_results = classify_documents_bounded(
        image_only_matcher,
        [
            ("scan-one.pdf", b"%PDF-1.7 scan-one", "other"),
            ("scan-two.pdf", b"%PDF-1.7 scan-two", "other"),
        ],
        isolate_pdf_parsing=False,
        reject_common_unsupported_format=True,
    )
    assert [item.detected_type for item in image_only_results] == ["unknown", "unknown"]

    unrelated_text = {
        b"%PDF-1.7 report": "Quarterly financial report and board meeting notes",
        b"%PDF-1.7 menu": "Restaurant menu with prices and opening hours",
    }
    unrelated_matcher = DocumentMatcher()
    monkeypatch.setattr(unrelated_matcher, "_pdf_text", unrelated_text.__getitem__)
    unrelated_results = classify_documents_bounded(
        unrelated_matcher,
        [
            ("report.pdf", b"%PDF-1.7 report", "other"),
            ("menu.pdf", b"%PDF-1.7 menu", "other"),
        ],
        isolate_pdf_parsing=False,
        reject_common_unsupported_format=True,
    )
    assert [item.detected_type for item in unrelated_results] == ["unknown", "unknown"]


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


def test_malaysia_airlines_electronic_ticket_receipt_is_a_ticket() -> None:
    text = """
    ELECTRONIC TICKET RECEIPT
    Passenger: SAMPLE TRAVELLER MR (ADT)
    Booking ref: EINDC4
    Ticket number: 232 2485729271
    From AHMEDABAD To KUALA LUMPUR Flight MH107 Departure 22:45 Arrival 06:45
    From KUALA LUMPUR To HO CHI MINH CITY Flight MH750 Departure 09:00 Arrival 10:00
    Operated by: MALAYSIA AIRLINES Booking status: OK
    """

    assert DocumentMatcher()._detect_type(text) == "flight_ticket"


def test_image_only_pdf_uses_bounded_ocr_fallback(monkeypatch) -> None:
    matcher = DocumentMatcher()
    reads = 0

    def read_image_only_pdf(_content: bytes):
        nonlocal reads
        reads += 1
        return document_matcher_module._PdfTextRead("", True)

    monkeypatch.setattr(matcher, "_read_pdf_text_with_pypdf", read_image_only_pdf)
    monkeypatch.setattr(
        matcher,
        "_ocr_validated_image_only_pdf",
        lambda _content: (
            "E-TICKET ITINERARY\nBooking reference: ABC123\nDeparture: DEL\nArrival: BKK"
        ),
    )

    result = matcher.classify(
        filename="ticket.pdf",
        content=b"%PDF-1.7\n%%EOF",
        expected_type="flight_ticket",
    )

    assert result.accepted is True
    assert result.detected_type == "flight_ticket"
    assert reads == 1


def test_unsafe_image_only_pdf_never_reaches_ocr(monkeypatch) -> None:
    matcher = DocumentMatcher()
    monkeypatch.setattr(
        matcher,
        "_read_pdf_text_with_pypdf",
        lambda _content: document_matcher_module._PdfTextRead("", False),
    )
    ocr_called = False

    def unexpected_ocr(_content: bytes) -> str:
        nonlocal ocr_called
        ocr_called = True
        return "ELECTRONIC TICKET RECEIPT"

    monkeypatch.setattr(matcher, "_ocr_validated_image_only_pdf", unexpected_ocr)

    result = matcher.classify(
        filename="unsafe.pdf",
        content=b"%PDF-1.7\n%%EOF",
        expected_type="flight_ticket",
    )

    assert result.accepted is False
    assert result.detected_type == "unknown"
    assert ocr_called is False


def test_pdfium_empty_text_layer_skips_expensive_pypdf_layout_extraction(
    monkeypatch,
) -> None:
    matcher = DocumentMatcher()

    class PageThatMustNotExtract:
        def extract_text(self) -> str:
            raise AssertionError("pypdf layout extraction should not run for image-only PDFs")

    reader = SimpleNamespace(
        is_encrypted=False,
        pages=[PageThatMustNotExtract()],
        root_object={},
    )
    monkeypatch.setattr(document_matcher_module, "PdfReader", lambda *_args, **_kwargs: reader)
    monkeypatch.setattr(matcher, "_has_active_pdf_features", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(matcher, "_extract_pdf_text_with_pdfium", lambda *_args, **_kwargs: "")

    read = matcher._read_pdf_text_with_pypdf(b"%PDF-1.7\n%%EOF")

    assert read == document_matcher_module._PdfTextRead("", True)


def test_pdfium_native_text_is_final_and_skips_pypdf_layout_extraction(
    monkeypatch,
) -> None:
    matcher = DocumentMatcher()

    class PageThatMustNotExtract:
        def extract_text(self) -> str:
            raise AssertionError("native PDFium text must not be parsed again")

    reader = SimpleNamespace(
        is_encrypted=False,
        pages=[PageThatMustNotExtract()],
        root_object={},
    )
    native_text = (
        "Flight summary\nBooking no. ABC123\nDeparture: Chennai\nDestination: Ho Chi Minh City"
    )
    monkeypatch.setattr(document_matcher_module, "PdfReader", lambda *_args, **_kwargs: reader)
    monkeypatch.setattr(matcher, "_has_active_pdf_features", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        matcher,
        "_extract_pdf_text_with_pdfium",
        lambda *_args, **_kwargs: native_text,
    )

    read = matcher._read_pdf_text_with_pypdf(b"%PDF-1.7\n%%EOF")

    assert read == document_matcher_module._PdfTextRead(native_text, True)


@pytest.mark.parametrize(
    "expected_type",
    [
        "flight_ticket_arrival",
        "flight_ticket_domestic",
        "flight_ticket_domestic_arrival",
    ],
)
def test_ticket_distribution_lanes_accept_a_verified_flight_ticket(
    monkeypatch,
    expected_type: str,
) -> None:
    matcher = DocumentMatcher()
    monkeypatch.setattr(
        matcher,
        "_pdf_text",
        lambda _content: (
            "Flight summary Booking no. ABC123 Departure: Chennai Destination: Ho Chi Minh City"
        ),
    )

    result = matcher.classify(
        filename="return-ticket.pdf",
        content=b"%PDF-1.7\n%%EOF",
        expected_type=expected_type,
    )

    assert result.accepted is True
    assert result.detected_type == "flight_ticket"


def test_validated_image_ocr_receives_its_own_time_budget(monkeypatch) -> None:
    matcher = DocumentMatcher()
    observed_timeout = 0.0

    class FakeImage:
        width = 900
        height = 1_200

        def thumbnail(self, _size: tuple[int, int]) -> None:
            raise AssertionError("bounded test image should not need resizing")

    class FakeBitmap:
        def to_pil(self) -> FakeImage:
            return FakeImage()

    class FakePage:
        def render(self, *, scale: float) -> FakeBitmap:
            assert scale == document_matcher_module.PDF_OCR_RENDER_SCALE
            return FakeBitmap()

    class FakeDocument:
        def __len__(self) -> int:
            return 1

        def __getitem__(self, index: int) -> FakePage:
            assert index == 0
            return FakePage()

    def image_to_string(
        _image: FakeImage,
        *,
        lang: str,
        config: str,
        timeout: float,
    ) -> str:
        nonlocal observed_timeout
        observed_timeout = timeout
        assert lang == "eng"
        assert config == "--oem 1 --psm 6"
        return "ELECTRONIC TICKET RECEIPT\nBooking ref: EINDC4\nTicket number: 2322485729271"

    monkeypatch.setattr(
        document_matcher_module,
        "pypdfium2",
        SimpleNamespace(PdfDocument=lambda _content: FakeDocument()),
    )
    monkeypatch.setitem(
        sys.modules,
        "pytesseract",
        SimpleNamespace(image_to_string=image_to_string),
    )

    text = matcher._ocr_validated_image_only_pdf(b"%PDF-1.7\n%%EOF")

    assert "ELECTRONIC TICKET RECEIPT" in text
    assert 6.0 <= observed_timeout <= document_matcher_module.MAX_PDF_OCR_SECONDS


def test_image_ocr_timeout_is_retryable_instead_of_unknown(monkeypatch) -> None:
    matcher = DocumentMatcher()

    class FakeImage:
        width = 900
        height = 1_200

        def thumbnail(self, _size: tuple[int, int]) -> None:
            return None

    fake_page = SimpleNamespace(
        render=lambda **_kwargs: SimpleNamespace(to_pil=lambda: FakeImage())
    )

    class FakeDocument:
        def __len__(self) -> int:
            return 1

        def __getitem__(self, index: int):
            assert index == 0
            return fake_page

    monkeypatch.setattr(
        document_matcher_module,
        "pypdfium2",
        SimpleNamespace(PdfDocument=lambda _content: FakeDocument()),
    )
    monkeypatch.setitem(
        sys.modules,
        "pytesseract",
        SimpleNamespace(
            image_to_string=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("OCR deadline")
            )
        ),
    )

    with pytest.raises(DocumentOcrUnavailableError):
        matcher._ocr_validated_image_only_pdf(b"%PDF-1.7\n%%EOF")


def test_isolated_ocr_timeout_marks_verification_chunk_retryable(monkeypatch) -> None:
    from app.infrastructure.documents import pdf_parser_sandbox

    monkeypatch.setattr(
        pdf_parser_sandbox,
        "classify_pdf_batch_isolated",
        lambda _jobs, **_kwargs: [
            {
                "original_filename": "ticket.pdf",
                "detected_type": "unknown",
                "accepted": False,
                "reason": PDF_OCR_RETRY_REASON,
                "text": "",
                "extracted_name": None,
                "extracted_passport_number": None,
                "extracted_reference": None,
            }
        ],
    )

    with pytest.raises(DocumentParserUnavailableError):
        classify_documents_bounded(
            DocumentMatcher(),
            [("ticket.pdf", b"%PDF-1.7\n%%EOF", "flight_ticket")],
            isolate_pdf_parsing=True,
        )


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


@pytest.mark.parametrize("detected_type", ["visa", "flight_ticket"])
def test_joined_reordered_filename_name_matches_for_every_distribution_type(
    detected_type: str,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    expected = _passenger(
        name="Aarav Devkumar Patel",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
    )
    conflicting = _passenger(
        name="Riya Shah",
        passport_number="R7654321",
        agency_id=agency_id,
        group_id=group_id,
    )
    passengers = [expected, conflicting]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)
    document = ClassifiedDocument(
        original_filename="Patel AaravDevkumar Ticket.pdf",
        detected_type=detected_type,
        accepted=True,
        reason="Accepted",
        text="Passenger name: Riya Shah Passport R7654321",
        extracted_name="Riya Shah",
        extracted_passport_number="R7654321",
        extracted_reference=None,
    )

    matches = matcher.match_all(document, passengers, index=index)

    assert [(match.passenger_id, match.status) for match in matches] == [(expected.id, "matched")]
    assert matches[0].reason.startswith("Filename exact passenger name")


def test_joined_reordered_filename_name_collision_fails_closed() -> None:
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
            ("Aarav Dev Patel", "P1234567"),
            ("Dev Aarav Patel", "P7654321"),
        )
    ]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)

    matches = matcher.match_all(
        _document(filename="Patel AaravDev Visa.pdf"),
        passengers,
        index=index,
    )

    assert len(matches) == 1
    assert matches[0].passenger_id is None
    assert matches[0].status == "needs_review"
    assert "ambiguous" in matches[0].reason


def test_joined_ocr_name_matches_after_generic_filename() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = _passenger(
        name="Aarav Devkumar Patel",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
    )
    matcher = DocumentMatcher()
    index = matcher.build_index([passenger], agency_id=agency_id, group_id=group_id)

    matches = matcher.match_all(
        _document(
            filename="electronic-ticket.pdf",
            text=("ELECTRONIC TICKET RECEIPT Booking ref ABC123 Passenger: Patel AaravDevkumar Mr"),
        ),
        [passenger],
        index=index,
    )

    assert [(match.passenger_id, match.status) for match in matches] == [(passenger.id, "matched")]
    assert matches[0].reason.startswith("PDF text exact passenger name")


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


def test_complete_combined_name_list_outranks_first_extracted_passenger() -> None:
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
            ("Maya Singh", "M1122334"),
        )
    ]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)
    document = _document(
        filename="combined-booking.pdf",
        text=("Flight summary Booking no. ABC123. Passengers: Asha Mehta, Ravi Shah, Maya Singh."),
    )
    document = ClassifiedDocument(
        original_filename=document.original_filename,
        detected_type="flight_ticket",
        accepted=True,
        reason="Accepted",
        text=document.text,
        extracted_name="Asha Mehta",
        extracted_passport_number=None,
        extracted_reference="ABC123",
    )

    matches = matcher.match_all(document, passengers, index=index)

    assert {match.passenger_id for match in matches} == {passenger.id for passenger in passengers}
    assert {match.status for match in matches} == {"matched"}


def test_combined_ticket_assigns_the_same_pdf_to_twenty_named_passengers() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    given_names = (
        "Aarav",
        "Vivaan",
        "Aditya",
        "Arjun",
        "Reyansh",
        "Ayaan",
        "Krishna",
        "Ishaan",
        "Shaurya",
        "Atharv",
        "Ananya",
        "Diya",
        "Myra",
        "Sara",
        "Aadhya",
        "Avni",
        "Kiara",
        "Ira",
        "Meera",
        "Riya",
    )
    passengers = [
        _passenger(
            name=f"{given} Traveller{index}",
            passport_number=f"P{index:07d}",
            agency_id=agency_id,
            group_id=group_id,
        )
        for index, given in enumerate(given_names, start=1)
    ]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)
    names = ", ".join(passenger.client_name for passenger in passengers)
    document = ClassifiedDocument(
        original_filename="combined-booking.pdf",
        detected_type="flight_ticket",
        accepted=True,
        reason="Accepted",
        text=f"Flight itinerary Booking ABC123 Passengers: {names}",
        extracted_name=passengers[0].client_name,
        extracted_passport_number=None,
        extracted_reference="ABC123",
    )

    matches = matcher.match_all(document, passengers, index=index)

    assert {match.passenger_id for match in matches} == {passenger.id for passenger in passengers}
    assert {match.status for match in matches} == {"matched"}


def test_cropped_ticket_manifest_matches_unique_names_when_middle_names_are_omitted() -> None:
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
            ("Aarav Devkumar Patel", "P1234567"),
            ("Maya Priyanka Shah", "R7654321"),
        )
    ]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)
    document = ClassifiedDocument(
        original_filename="return-flight-ticket.pdf",
        detected_type="flight_ticket",
        accepted=True,
        reason="Accepted",
        text=(
            "TRAVEL ITINERARY\n"
            "2. Passenger(s) Information\n"
            "Passenger Name(s) Seat(s)\n"
            "PATEL, AARAV VJ140 --\n"
            "SHAH, MAYA VJ971 --\n"
            "3. Flight Information\n"
            "Flight Number Date Depart Arrive"
        ),
        extracted_name=None,
        extracted_passport_number=None,
        extracted_reference="ABC123",
    )

    matches = matcher.match_all(document, passengers, index=index)

    assert {match.passenger_id for match in matches} == {passenger.id for passenger in passengers}
    assert {match.status for match in matches} == {"matched"}
    assert {match.confidence for match in matches} == {0.88}


def test_cropped_ticket_manifest_shared_name_pair_fails_closed() -> None:
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
            ("Aarav Dev Patel", "P1234567"),
            ("Aarav Kumar Patel", "R7654321"),
        )
    ]
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)
    document = ClassifiedDocument(
        original_filename="return-flight-ticket.pdf",
        detected_type="flight_ticket",
        accepted=True,
        reason="Accepted",
        text=(
            "TRAVEL ITINERARY\n"
            "Passenger(s) Information\n"
            "Passenger Name(s) Seat(s)\n"
            "PATEL, AARAV VJ140 --\n"
            "Flight Information\n"
            "Flight Number Date Depart Arrive"
        ),
        extracted_name=None,
        extracted_passport_number=None,
        extracted_reference="ABC123",
    )

    matches = matcher.match_all(document, passengers, index=index)

    assert len(matches) == 1
    assert matches[0].passenger_id is None
    assert matches[0].status == "needs_review"


def test_flattened_ticket_manifest_rows_cannot_synthesize_a_third_passenger() -> None:
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
            ("Aarav Devkumar Patel", "P1234567"),
            ("Maya Priyanka Shah", "R7654321"),
            ("Aarav Zed Shah", "T2345678"),
        )
    ]
    false_passenger_id = passengers[2].id
    matcher = DocumentMatcher()
    index = matcher.build_index(passengers, agency_id=agency_id, group_id=group_id)
    document = ClassifiedDocument(
        original_filename="flattened-manifest.pdf",
        detected_type="flight_ticket",
        accepted=True,
        reason="Accepted",
        text=(
            "TRAVEL ITINERARY\n"
            "Passenger(s) Information\n"
            "Passenger Name(s) Seat(s)\n"
            "PATEL, AARAV SHAH, MAYA VJ140 --\n"
            "Flight Information\n"
            "Flight Number Date Depart Arrive"
        ),
        extracted_name=None,
        extracted_passport_number=None,
        extracted_reference="ABC123",
    )

    matches = matcher.match_all(document, passengers, index=index)

    assert false_passenger_id not in {
        match.passenger_id for match in matches if match.status == "matched"
    }


def test_partial_name_pair_outside_ticket_manifest_is_not_identity_evidence() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger = _passenger(
        name="Aarav Devkumar Patel",
        passport_number="P1234567",
        agency_id=agency_id,
        group_id=group_id,
    )
    matcher = DocumentMatcher()
    index = matcher.build_index([passenger], agency_id=agency_id, group_id=group_id)
    document = ClassifiedDocument(
        original_filename="return-flight-ticket.pdf",
        detected_type="flight_ticket",
        accepted=True,
        reason="Accepted",
        text="Travel agent contact: Patel, Aarav. Booking reference ABC123.",
        extracted_name=None,
        extracted_passport_number=None,
        extracted_reference="ABC123",
    )

    matches = matcher.match_all(document, [passenger], index=index)

    assert len(matches) == 1
    assert matches[0].passenger_id is None
    assert matches[0].status == "needs_review"


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
