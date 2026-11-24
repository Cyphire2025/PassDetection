"""Focused type detection policy; no parser or I/O side effects."""

from __future__ import annotations

import re

from app.infrastructure.documents.document_matcher_models import _VisaDocumentFacts
from app.infrastructure.documents.document_matcher_rules import (
    _NON_TRAVEL_DOCUMENT_PATTERNS,
    MAX_PDF_TEXT_CHARS,
    PASSPORT_TERMS,
    PAYMENT_TERMS,
    TICKET_BOOKING_TERMS,
    TICKET_CORE_TERMS,
    TICKET_FLIGHT_TERMS,
    TICKET_ROUTE_TERMS,
    TICKET_TRAVEL_TERMS,
    VISA_APPLICATION_TERMS,
    VISA_AUTHORITY_TERMS,
    VISA_CORE_TERMS,
    VISA_VALIDITY_TERMS,
)
from app.infrastructure.documents.document_text_fields import DocumentTextFields


class DocumentTextClassifier(DocumentTextFields):
    def _detect_type(
        self,
        text: str,
        *,
        visa_facts: _VisaDocumentFacts | None = None,
    ) -> str:
        normalized = self._normalize(text)
        if not normalized:
            return "unknown"
        if any(re.search(pattern, normalized) for pattern in _NON_TRAVEL_DOCUMENT_PATTERNS):
            return "unknown"
        facts = visa_facts or self._extract_visa_facts(text)
        ticket_has_structure = self._has_ticket_structure(text)
        visa_has_structure = self._has_visa_structure(text, visa_facts=facts)
        if "application status" in normalized and not visa_has_structure:
            return "unknown"
        if "invoice" in normalized and not ticket_has_structure:
            return "unknown"

        payment_score = self._term_score(normalized, PAYMENT_TERMS)
        ticket_core_score = self._term_score(normalized, TICKET_CORE_TERMS)
        ticket_booking_score = self._term_score(normalized, TICKET_BOOKING_TERMS)
        ticket_flight_score = self._term_score(normalized, TICKET_FLIGHT_TERMS)
        ticket_route_score = self._term_score(normalized, TICKET_ROUTE_TERMS)
        ticket_travel_score = self._term_score(normalized, TICKET_TRAVEL_TERMS)
        ticket_operational_score = (
            ticket_booking_score
            + ticket_flight_score
            + min(ticket_route_score, 2)
            + min(ticket_travel_score, 2)
        )
        # Some airline booking summaries omit a literal "e-ticket" or
        # "itinerary" heading even though they contain a value-bearing PNR,
        # passenger sectors, a real route/flight, and check-in/seat details.
        # Keep the established heading path unchanged, and admit the heading-
        # free layout only when every independent operational category is
        # present. ``ticket_has_structure`` still requires actual booking and
        # route/flight values, so labels, generic travel prose, and filenames
        # alone remain fail-closed.
        ticket_has_operational_manifest = (
            ticket_booking_score >= 1
            and ticket_flight_score >= 1
            and ticket_route_score >= 1
            and ticket_travel_score >= 2
        )
        ticket_is_conclusive = ticket_has_structure and (
            ticket_core_score >= 1 or ticket_has_operational_manifest
        )

        visa_application_score = self._term_score(normalized, VISA_APPLICATION_TERMS)

        if ticket_is_conclusive and not (payment_score >= 3 and ticket_operational_score < 4):
            return "flight_ticket"
        if visa_application_score >= 1 and not visa_has_structure:
            return "unknown"
        if payment_score >= 2 and not visa_has_structure:
            return "unknown"
        if visa_has_structure:
            return "visa"

        passport_score = self._term_score(normalized, PASSPORT_TERMS)
        if passport_score >= 3 and not facts.has_heading and not ticket_is_conclusive:
            return "passport"
        return "unknown"

    def _has_visa_structure(
        self,
        text: str,
        *,
        visa_facts: _VisaDocumentFacts | None = None,
    ) -> bool:
        facts = visa_facts or self._extract_visa_facts(text)
        has_validity = bool(facts.validity_dates)

        # This is a boolean issuance-fact quorum, not a confidence score.  A
        # heading plus a document reference and another issuance fact covers
        # grant notices, while layouts without a labeled reference require the
        # stronger passport + validity + entry/authority combination.
        referenced_issuance = bool(facts.reference) and any(
            (
                has_validity,
                facts.has_entry_information,
                bool(facts.passport_number),
                facts.has_authority,
            )
        )
        identity_issuance = (
            bool(facts.passport_number)
            and has_validity
            and (facts.has_entry_information or facts.has_authority)
        )
        return facts.has_heading and (referenced_issuance or identity_issuance)

    def _extract_visa_facts(self, text: str) -> _VisaDocumentFacts:
        normalized = self._normalize(text)
        return _VisaDocumentFacts(
            name=self._extract_labeled_name(text),
            passport_number=self._extract_passport_number(text),
            reference=self._extract_visa_reference(text),
            validity_dates=self._extract_visa_dates(text),
            has_heading=self._has_visa_heading(text),
            has_authority=self._term_score(normalized, VISA_AUTHORITY_TERMS) >= 1,
            has_entry_information=self._has_visa_entry_information(text),
        )

    def _has_visa_heading(self, text: str) -> bool:
        for line in self._text_lines(text):
            normalized = self._normalize(line)
            if not normalized:
                continue
            has_grant_heading = "visa grant" in normalized or "grant notice" in normalized
            has_explicit_heading = any(
                term in normalized for term in ("electronic visa", "e visa", "entry permit")
            )
            blocked_context = any(
                term in normalized
                for term in ("application fee", "application form", "payment", "receipt")
            )
            if has_grant_heading or (has_explicit_heading and not blocked_context):
                return True
            if normalized in {"visa", "electronic visa", "e visa"}:
                return True
        return False

    def _has_visa_entry_information(self, text: str) -> bool:
        entry_value = self._has_labeled_value(
            text,
            (
                r"(?:number\s+of\s+entries|entries|good\s+for\s+single\s*/?\s*multiple\s+entries|"
                r"sử\s+dụng\s+một\s*/?\s*nhiều\s+lần)"
            ),
            r"(?:single|multiple|one|two|một|nhiều|[1-9]\d?)",
        )
        stay_value = self._has_labeled_value(
            text,
            r"(?:duration\s+of\s+stay|permitted\s+to\s+stay|thời\s+hạn\s+tạm\s+trú)",
            r"[1-9]\d{0,3}(?:\s+(?:day|days|month|months|ngày|tháng))?",
        )
        return entry_value or stay_value

    def _unsupported_format_signature(self, text: str) -> tuple[str, ...]:
        """Return deterministic structural anchors for repeated unknown layouts."""

        normalized = self._normalize(text)
        if not normalized:
            return ()
        groups: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("visa", VISA_CORE_TERMS),
            ("ticket", TICKET_CORE_TERMS),
            ("name", ("full name", "applicant name", "passenger name", "họ tên")),
            ("passport", ("passport number", "passport no", "số hộ chiếu")),
            (
                "reference",
                ("visa number", "grant number", "document reference", "reference number", "code"),
            ),
            ("validity", VISA_VALIDITY_TERMS),
            ("authority", VISA_AUTHORITY_TERMS),
            ("booking", TICKET_BOOKING_TERMS),
            ("route", TICKET_ROUTE_TERMS),
            ("payment", PAYMENT_TERMS),
        )
        return tuple(name for name, terms in groups if self._term_score(normalized, terms) >= 1)

    def _has_ticket_structure(self, text: str) -> bool:
        booking_value = self._has_labeled_value(
            text,
            r"(?:pnr|booking\s+(?:no|number|ref|reference)|reservation\s+code|record\s+locator)",
            (
                r"(?!(?:flight|ticket|departure|arrival|origin|destination|passenger|"
                r"booking|pnr|date|name)\b)[A-Z0-9]{5,12}"
            ),
        )
        ticket_value = self._has_labeled_value(
            text,
            r"(?:ticket\s+(?:no|number))",
            r"(?=[A-Z0-9-]{6,24}\b)(?=[A-Z0-9-]*\d)[A-Z0-9-]+",
        )
        flight_value = self._has_labeled_value(
            text,
            r"(?:flight(?:\s+(?:no|number))?)",
            r"[A-Z0-9]{2,3}\s*-?\s*\d{1,4}[A-Z]?",
        )
        sector_value = bool(
            re.search(
                r"\b[A-Z]{3}\s*[-/]\s*[A-Z]{3}\b",
                " ".join(text.split())[:MAX_PDF_TEXT_CHARS],
                flags=re.IGNORECASE,
            )
        )
        standalone_flight_value = bool(
            re.search(
                r"\b(?:[A-Z]{2}|(?=[A-Z0-9]{2,3}\b)[A-Z0-9]*\d[A-Z0-9]*)"
                r"\s*-?\s*\d{1,4}[A-Z]?\b",
                " ".join(text.split())[:MAX_PDF_TEXT_CHARS],
                flags=re.IGNORECASE,
            )
        )
        departure_value = self._has_route_value(text, "departure|departing|origin")
        arrival_value = self._has_route_value(text, "arrival|destination")
        route_pair = departure_value and arrival_value
        if "boarding pass" in self._normalize(text):
            return flight_value and (departure_value or arrival_value)
        return (booking_value or ticket_value) and (
            route_pair or flight_value or (sector_value and standalone_flight_value)
        )

    def _has_route_value(self, text: str, labels: str) -> bool:
        return self._has_labeled_value(
            text,
            rf"(?:{labels})",
            (
                r"(?!(?:arrival|departure|departing|origin|destination|flight|ticket|pnr|booking)\b)"
                r"(?:[A-Z]{3}\b|[A-Za-z][A-Za-z .'-]{2,40})"
            ),
        )
