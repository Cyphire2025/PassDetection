"""Bounded document classification and deterministic passenger matching."""

from __future__ import annotations

import re
import time
import unicodedata
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from app.domain.entities.entities import PassportSubmission
from app.domain.value_objects.personnel_codes import (
    prefixed_agent_employee_code,
    prefixed_staff_code,
)

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - keeps local tooling usable until deps are installed
    PdfReader = None

try:
    import pypdfium2
except ImportError:  # pragma: no cover - keeps local tooling usable until deps are installed
    pypdfium2 = None


DOCUMENT_TYPES = {"visa", "flight_ticket", "other"}
SUPPORTED_TRAVEL_DOCUMENT_TYPES = frozenset({"visa", "flight_ticket"})

MAX_PDF_PAGES_TO_INSPECT = 5
MAX_PDF_TOTAL_PAGES = 200
MAX_PDF_PAGE_TEXT_CHARS = 40_000
MAX_PDF_TEXT_CHARS = 120_000
MAX_PDF_SOURCE_BYTES = 16 * 1024 * 1024
MAX_PDF_PARSE_SECONDS = 3.0
MAX_PDF_OCR_PAGES = 2
MAX_PDF_OCR_PIXELS = 4_000_000
PDF_OCR_RENDER_SCALE = 1.5
MAX_PASSENGER_NAMES = 12
MAX_PASSENGER_IDENTIFIERS = 96
MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER = 24
MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST = 36_000
MAX_SUPPLEMENTAL_IDENTIFIER_INPUTS = 72_000
MAX_NAME_TOKENS = 8
MAX_FUZZY_CANDIDATES = 32

VISA_CORE_TERMS = (
    "visa",
    "evisa",
    "e-visa",
    "electronic visa",
    "entry permit",
    "visa grant",
    "grant notice",
)
VISA_IDENTITY_TERMS = (
    "visa number",
    "visa no",
    "visa type",
    "visa category",
    "grant number",
    "entry permit number",
    "travel document number",
)
VISA_VALIDITY_TERMS = (
    "number of entries",
    "multiple entries",
    "single entry",
    "valid from",
    "valid until",
    "date of issue",
    "date of expiry",
    "duration of stay",
    "permitted to stay",
)
VISA_AUTHORITY_TERMS = (
    "immigration",
    "ministry of interior",
    "ministry of public security",
    "department of immigration",
    "immigration department",
    "immigration authority",
    "vietnam immigration department",
)
VISA_APPLICATION_TERMS = (
    "application received",
    "application status",
    "application form",
    "application submitted",
    "appointment confirmation",
)
PAYMENT_TERMS = (
    "payment confirmation",
    "payment receipt",
    "fee charge payment",
    "application fee",
    "service fee",
    "transaction id",
    "payment details",
    "payment method",
    "total amount",
    "amount paid",
    "tax payment",
    "invoice",
    "receipt",
)

TICKET_CORE_TERMS = (
    "e-ticket",
    "electronic ticket",
    "flight ticket",
    "flight tickets",
    "itinerary",
    "travel summary",
    "ticket itinerary",
    "itinerary receipt",
    "passenger itinerary",
    "passenger receipt",
    "boarding pass",
    "booking confirmation",
    "ticket number",
    "ticket no",
)
TICKET_BOOKING_TERMS = (
    "pnr",
    "booking no",
    "booking number",
    "booking reference",
    "reservation code",
    "record locator",
)
TICKET_FLIGHT_TERMS = (
    "flight number",
    "flight no",
    "flight summary",
    "operated by",
    "airline",
    "carrier",
    "sector",
)
TICKET_ROUTE_TERMS = (
    "departure",
    "arrival",
    "departing",
    "origin",
    "destination",
)
TICKET_TRAVEL_TERMS = (
    "boarding",
    "check in",
    "check-in",
    "gate",
    "seat",
    "checked baggage",
    "carry-on baggage",
)
PASSPORT_TERMS = ("passport", "nationality", "place of birth", "date of expiry")

_PASSPORT_KEYS = frozenset(
    {"passport", "passport_no", "passport_num", "passport_number", "passportnumber"}
)
_GIVEN_NAME_KEYS = frozenset({"first_name", "forename", "given_name", "given_names"})
_SURNAME_KEYS = frozenset({"family_name", "last_name", "surname"})
_FULL_NAME_KEYS = frozenset(
    {
        "client_name",
        "employee_name",
        "full_name",
        "name",
        "passenger_name",
        "recipient_name",
        "staff_name",
        "staffname",
        "traveller_name",
        "traveler_name",
    }
)
_STAFF_CODE_KEYS = frozenset(
    {"employee_code", "employee_id", "staff_code", "staff_id", "staffcode"}
)
_AGENT_CODE_KEYS = frozenset({"agent_code", "agent_employee_code", "agent_id", "employee_code"})
_IDENTIFIER_KEY_TOKENS = frozenset(
    {"code", "id", "identifier", "no", "number", "ref", "reference", "serial"}
)
_IDENTIFIER_KEY_EXCLUSIONS = frozenset(
    {
        "agency_id",
        "batch_id",
        "broadcast_group_id",
        "booking_no",
        "booking_number",
        "booking_reference",
        "contact_no",
        "contact_number",
        "date_of_birth",
        "date_of_expiry",
        "date_of_issue",
        "detail_id",
        "document_id",
        "dob",
        "doe",
        "doi",
        "family_group_id",
        "group_id",
        "mobile_no",
        "mobile_number",
        "passenger_id",
        "passport_no",
        "passport_num",
        "passport_number",
        "phone_number",
        "pnr",
        "qualifier_selection_id",
        "question_id",
        "recipient_id",
        "row_number",
        "source_order",
        "source_row",
        "submission_id",
        "ticket_no",
        "ticket_number",
        "transaction_id",
    }
)
_DOCUMENT_FILENAME_WORDS = frozenset(
    {
        "document",
        "evisa",
        "flight",
        "itinerary",
        "pdf",
        "ticket",
        "visa",
    }
)
_NAME_NOISE_TOKENS = frozenset(
    {
        "adult",
        "arrival",
        "booking",
        "child",
        "date",
        "departure",
        "document",
        "female",
        "flight",
        "gender",
        "infant",
        "male",
        "miss",
        "mr",
        "mrs",
        "ms",
        "passenger",
        "passport",
        "ticket",
        "visa",
    }
)

_NON_TRAVEL_DOCUMENT_PATTERNS = (
    r"\b(?:thailand\s+)?digital\s+arrival\s+card\b",
    r"\bnot\s+(?:a|an)\s+(?:e-?visa|visa)\b",
    r"\b(?:visa\s+)?application\s+form\b",
    r"\bapplication\s+received\b",
    r"\bapplication\s+submitted\b",
    r"\bappointment\s+confirmation\b",
    r"\b(?:travel\s+|insurance\s+|travel\s+insurance\s+)?claim\s+form\b",
    r"\btravel\s+insurance\s+claim\b",
    r"\b(?:price\s+)?quotation\b",
    r"\bprice\s+quote\b",
    r"\bpro\s+forma\s+invoice\b",
    r"\b(?:blank|sample)\s+(?:application|claim|form|template)\b",
)

_DATE_VALUE_PATTERN = (
    r"(?:\d{1,4}[./-]\d{1,2}[./-]\d{1,4}"
    r"|\d{1,2}\s+[^\W\d_]{3,15}\s+\d{2,4}"
    r"|[^\W\d_]{3,15}\s+\d{1,2},?\s+\d{2,4})"
)


@dataclass(frozen=True, slots=True)
class ClassifiedDocument:
    original_filename: str
    detected_type: str
    accepted: bool
    reason: str
    text: str
    extracted_name: str | None
    extracted_passport_number: str | None
    extracted_reference: str | None


@dataclass(frozen=True, slots=True)
class _VisaDocumentFacts:
    """Deterministic fields and structural facts extracted before classification."""

    name: str | None
    passport_number: str | None
    reference: str | None
    validity_dates: tuple[str, ...]
    has_heading: bool
    has_authority: bool
    has_entry_information: bool


@dataclass(frozen=True, slots=True)
class MatchResult:
    passenger_id: uuid.UUID | None
    confidence: float
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class PassengerIdentifier:
    """One request-scoped identity alias sourced from linked, tenant-owned data."""

    passenger_id: uuid.UUID
    agency_id: uuid.UUID
    group_id: uuid.UUID
    kind: str
    value: str
    source: str


@dataclass(frozen=True, slots=True)
class _IdentifierOwner:
    passenger_id: uuid.UUID
    kind: str
    source: str


@dataclass(frozen=True, slots=True)
class _PassengerProfile:
    passenger_id: uuid.UUID
    names: tuple[tuple[str, ...], ...]


@dataclass(slots=True)
class DocumentMatchIndex:
    """Request-local immutable-in-practice lookup tables for one passenger scope."""

    passengers_by_id: dict[uuid.UUID, PassportSubmission]
    profiles_by_id: dict[uuid.UUID, _PassengerProfile]
    passports: dict[str, tuple[uuid.UUID, ...]]
    names: dict[tuple[str, ...], tuple[uuid.UUID, ...]]
    identifiers: dict[str, tuple[_IdentifierOwner, ...]]
    name_token_passengers: dict[str, tuple[uuid.UUID, ...]]
    name_lengths: tuple[int, ...]


class DocumentParserUnavailableError(RuntimeError):
    """Transient parser-capacity failure that callers should expose as retryable."""


class UnsupportedDocumentBatchFormatError(RuntimeError):
    """A repeated, readable batch layout could not be verified safely."""


def _raise_for_common_unsupported_format(
    matcher: DocumentMatcher,
    jobs: list[tuple[str, bytes, str]],
    classifications: list[ClassifiedDocument],
) -> None:
    if len(classifications) < 2 or any(item.detected_type != "unknown" for item in classifications):
        return
    signatures = [matcher._unsupported_format_signature(item.text) for item in classifications]
    if (
        not signatures[0]
        or len(signatures[0]) < 3
        or any(signature != signatures[0] for signature in signatures[1:])
    ):
        return

    expected_types = {expected_type for _filename, _content, expected_type in jobs}
    if expected_types == {"visa"}:
        target = "a visa"
    elif expected_types == {"flight_ticket"}:
        target = "a flight ticket"
    else:
        target = "a visa or flight ticket"
    raise UnsupportedDocumentBatchFormatError(
        "Unsupported common document format: these PDFs share a readable layout "
        f"that could not be verified as {target}. No files were stored."
    )


def classify_documents_bounded(
    matcher: DocumentMatcher,
    jobs: list[tuple[str, bytes, str]],
    *,
    isolate_pdf_parsing: bool,
    batch_timeout_seconds: float | None = None,
    reject_common_unsupported_format: bool = False,
) -> list[ClassifiedDocument]:
    """Classify a request batch, isolating untrusted parsing when requested.

    Test doubles and explicitly overridden parser methods retain the direct path
    so deterministic unit tests do not spawn child processes.  Production route
    instances use the exact matcher class and therefore always take the sandbox.
    """

    use_sandbox = (
        isolate_pdf_parsing
        and type(matcher) is DocumentMatcher
        and "_pdf_text" not in matcher.__dict__
    )
    if not use_sandbox:
        classifications = [
            matcher.classify(
                filename=filename,
                content=content,
                expected_type=expected_type,
            )
            for filename, content, expected_type in jobs
        ]
        if reject_common_unsupported_format:
            _raise_for_common_unsupported_format(matcher, jobs, classifications)
        return classifications

    from app.infrastructure.documents.pdf_parser_sandbox import (
        classify_pdf_batch_isolated,
    )

    payloads = (
        classify_pdf_batch_isolated(jobs)
        if batch_timeout_seconds is None
        else classify_pdf_batch_isolated(
            jobs,
            batch_timeout_seconds=batch_timeout_seconds,
        )
    )
    classifications: list[ClassifiedDocument] = []
    for (filename, _content, _expected_type), payload in zip(jobs, payloads, strict=True):
        detected_type = payload.get("detected_type")
        accepted = payload.get("accepted")
        reason = payload.get("reason")
        text = payload.get("text")
        extracted_name = payload.get("extracted_name")
        extracted_passport_number = payload.get("extracted_passport_number")
        extracted_reference = payload.get("extracted_reference")
        if reason in {
            "PDF parser capacity is temporarily exhausted",
            "PDF parser service is temporarily unavailable",
        }:
            raise DocumentParserUnavailableError(
                "PDF verification is temporarily busy; retry the upload"
            )
        payload_is_valid = (
            detected_type in {"visa", "flight_ticket", "passport", "unknown"}
            and isinstance(accepted, bool)
            and isinstance(reason, str)
            and isinstance(text, str)
            and (extracted_name is None or isinstance(extracted_name, str))
            and (extracted_passport_number is None or isinstance(extracted_passport_number, str))
            and (extracted_reference is None or isinstance(extracted_reference, str))
        )
        if not payload_is_valid:
            classifications.append(
                ClassifiedDocument(
                    original_filename=filename,
                    detected_type="unknown",
                    accepted=False,
                    reason="PDF parser returned an invalid result",
                    text="",
                    extracted_name=None,
                    extracted_passport_number=None,
                    extracted_reference=None,
                )
            )
            continue
        classifications.append(
            ClassifiedDocument(
                original_filename=filename,
                detected_type=cast(str, detected_type),
                accepted=cast(bool, accepted),
                reason=cast(str, reason),
                text=cast(str, text),
                extracted_name=cast(str | None, extracted_name),
                extracted_passport_number=cast(str | None, extracted_passport_number),
                extracted_reference=cast(str | None, extracted_reference),
            )
        )
    if reject_common_unsupported_format:
        _raise_for_common_unsupported_format(matcher, jobs, classifications)
    return classifications


class DocumentMatcher:
    """Strict classifier plus deterministic, ambiguity-safe passenger matcher."""

    def classify(self, *, filename: str, content: bytes, expected_type: str) -> ClassifiedDocument:
        if expected_type not in DOCUMENT_TYPES:
            raise ValueError("Unsupported document type")
        if not filename.lower().endswith(".pdf") or not content.startswith(b"%PDF"):
            return ClassifiedDocument(
                filename,
                "unknown",
                False,
                "Only PDF files are accepted",
                "",
                None,
                None,
                None,
            )

        # The filename is intentionally excluded from classification. A file
        # named VISA.pdf must not turn an unrelated or unreadable PDF into a visa.
        text = self._pdf_text(content)
        visa_facts = self._extract_visa_facts(text)
        detected_type = self._detect_type(text, visa_facts=visa_facts)
        accepted = expected_type == "other" or detected_type == expected_type
        reason = "Accepted"
        if not accepted:
            if detected_type == "unknown":
                reason = f"Could not verify this PDF as a {self._label(expected_type)}"
            else:
                reason = (
                    f"Expected {self._label(expected_type)} but detected "
                    f"{self._label(detected_type)}"
                )

        return ClassifiedDocument(
            original_filename=filename,
            detected_type=detected_type,
            accepted=accepted,
            reason=reason,
            text=text,
            extracted_name=visa_facts.name or self._extract_name(text, detected_type),
            extracted_passport_number=visa_facts.passport_number,
            extracted_reference=self._extract_reference(text),
        )

    def build_index(
        self,
        passengers: list[PassportSubmission],
        *,
        agency_id: uuid.UUID | None = None,
        group_id: uuid.UUID | None = None,
        supplemental_identifiers: Iterable[PassengerIdentifier] = (),
    ) -> DocumentMatchIndex:
        """Build bounded lookup tables once for a verify/upload request."""

        scoped_passengers = {
            passenger.id: passenger
            for passenger in passengers
            if (agency_id is None or passenger.agency_id == agency_id)
            and (group_id is None or passenger.group_id == group_id)
        }
        passport_owners: dict[str, set[uuid.UUID]] = defaultdict(set)
        name_owners: dict[tuple[str, ...], set[uuid.UUID]] = defaultdict(set)
        identifier_owners: dict[str, set[_IdentifierOwner]] = defaultdict(set)
        name_token_owners: dict[str, set[uuid.UUID]] = defaultdict(set)
        profiles: dict[uuid.UUID, _PassengerProfile] = {}
        direct_identifier_counts: dict[uuid.UUID, int] = {}

        for passenger_id, passenger in scoped_passengers.items():
            fields = self._passport_fields(passenger)
            names = self._normalized_passenger_names(passenger, fields)
            profiles[passenger_id] = _PassengerProfile(passenger_id, names)
            for name in names:
                name_owners[name].add(passenger_id)
                for token in set(name):
                    if token not in _NAME_NOISE_TOKENS and len(token) > 1:
                        name_token_owners[token].add(passenger_id)

            for raw_value in self._mapping_values(fields, _PASSPORT_KEYS):
                if value := self._normalize_identifier(raw_value):
                    passport_owners[value].add(passenger_id)

            direct_mappings: tuple[tuple[Mapping[str, Any], str], ...] = (
                (dict(getattr(passenger, "staff_metadata", None) or {}), "group Excel"),
                (fields, "passenger details"),
            )
            identifier_count = 0
            for mapping, source in direct_mappings:
                for value, kind in self._identifier_aliases(mapping):
                    owner = _IdentifierOwner(passenger_id, kind, source)
                    owners = identifier_owners[value]
                    if owner not in owners:
                        owners.add(owner)
                        identifier_count += 1
                    if identifier_count >= MAX_PASSENGER_IDENTIFIERS:
                        break
                if identifier_count >= MAX_PASSENGER_IDENTIFIERS:
                    break
            if identifier_count < MAX_PASSENGER_IDENTIFIERS:
                for answer in (
                    list(getattr(passenger, "custom_answers", None) or [])
                    + list(getattr(passenger, "custom_detail_answers", None) or [])
                )[:40]:
                    if not isinstance(answer, Mapping):
                        continue
                    label = answer.get("label")
                    value = answer.get("value")
                    for alias, kind in self._identifier_aliases({str(label or ""): value}):
                        owner = _IdentifierOwner(passenger_id, kind, "group details")
                        owners = identifier_owners[alias]
                        if owner not in owners:
                            owners.add(owner)
                            identifier_count += 1
                        if identifier_count >= MAX_PASSENGER_IDENTIFIERS:
                            break
                    if identifier_count >= MAX_PASSENGER_IDENTIFIERS:
                        break
            direct_identifier_counts[passenger_id] = identifier_count

        supplemental_counts: dict[uuid.UUID, int] = defaultdict(int)
        supplemental_total = 0
        for input_index, supplemental in enumerate(supplemental_identifiers):
            if (
                input_index >= MAX_SUPPLEMENTAL_IDENTIFIER_INPUTS
                or supplemental_total >= MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST
            ):
                break
            passenger = scoped_passengers.get(supplemental.passenger_id)
            if (
                passenger is None
                or supplemental_counts[supplemental.passenger_id]
                >= MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER
                or direct_identifier_counts.get(supplemental.passenger_id, 0)
                + supplemental_counts[supplemental.passenger_id]
                >= MAX_PASSENGER_IDENTIFIERS
                or supplemental.agency_id != passenger.agency_id
                or supplemental.group_id != passenger.group_id
                or (agency_id is not None and supplemental.agency_id != agency_id)
                or (group_id is not None and supplemental.group_id != group_id)
            ):
                continue
            if value := self._normalize_identifier(supplemental.value):
                owner = _IdentifierOwner(
                    supplemental.passenger_id,
                    self._safe_identifier_kind(supplemental.kind),
                    self._safe_identifier_source(supplemental.source),
                )
                owners = identifier_owners[value]
                if owner in owners:
                    continue
                owners.add(owner)
                supplemental_counts[supplemental.passenger_id] += 1
                supplemental_total += 1

        return DocumentMatchIndex(
            passengers_by_id=scoped_passengers,
            profiles_by_id=profiles,
            passports=self._freeze_uuid_index(passport_owners),
            names=self._freeze_name_index(name_owners),
            identifiers={
                value: tuple(
                    sorted(
                        owners,
                        key=lambda owner: (str(owner.passenger_id), owner.kind, owner.source),
                    )
                )
                for value, owners in identifier_owners.items()
            },
            name_token_passengers=self._freeze_uuid_index(name_token_owners),
            name_lengths=tuple(sorted({len(name) for name in name_owners}, reverse=True)),
        )

    def stored_identifier_aliases(
        self,
        mapping: Mapping[str, Any],
    ) -> tuple[tuple[str, str], ...]:
        """Expose the canonical bounded alias policy to scoped data loaders."""

        return tuple(self._identifier_aliases(mapping))

    def match(
        self,
        document: ClassifiedDocument,
        passengers: list[PassportSubmission],
        *,
        index: DocumentMatchIndex | None = None,
    ) -> MatchResult:
        prepared = index or self.build_index(passengers)
        matches = self.match_all(document, passengers, index=prepared)
        automatic = [match for match in matches if match.status == "matched"]
        if len(automatic) == 1:
            return automatic[0]
        if len(automatic) > 1:
            return MatchResult(
                None,
                max(match.confidence for match in automatic),
                "needs_review",
                "Multiple passengers were identified; manual review is required",
            )
        return (
            matches[0]
            if matches
            else MatchResult(
                None,
                0.0,
                "needs_review",
                "No passenger match found",
            )
        )

    def match_all(
        self,
        document: ClassifiedDocument,
        passengers: list[PassportSubmission],
        *,
        index: DocumentMatchIndex | None = None,
    ) -> list[MatchResult]:
        """Return every strongly evidenced passenger in a combined document."""

        prepared = index or self.build_index(passengers)
        if not prepared.passengers_by_id:
            return [MatchResult(None, 0.0, "needs_review", "No passenger match found")]

        filename = Path(document.original_filename).stem
        filename_identifier_values = self._filename_identifier_values(filename)
        passport_matches, ambiguity = self._resolve_uuid_values(
            filename_identifier_values,
            prepared.passports,
            confidence=0.995,
            reason="Filename Passport number uniquely matched",
            ambiguity_reason="Filename passport number matches multiple passengers",
        )
        filename_ambiguities = [ambiguity] if ambiguity is not None else []

        filename_words = self._name_words(filename)
        filename_name_matches, ambiguity = self._resolve_name_windows(
            filename_words,
            prepared,
            confidence=0.97,
            reason="Filename exact passenger name uniquely matched",
            ambiguity_reason="Filename passenger name matches multiple passengers",
        )
        if ambiguity is not None:
            filename_ambiguities.append(ambiguity)

        filename_identifier_matches, ambiguity = self._resolve_identifier_values(
            filename_identifier_values,
            prepared.identifiers,
            confidence=0.93,
            prefix="Filename",
        )
        if ambiguity is not None:
            filename_ambiguities.append(ambiguity)

        filename_match_groups = [
            matches
            for matches in (
                passport_matches,
                filename_name_matches,
                filename_identifier_matches,
            )
            if matches
        ]
        filename_id_sets = [
            {match.passenger_id for match in matches if match.passenger_id}
            for matches in filename_match_groups
        ]
        if filename_ambiguities or (
            len(filename_id_sets) > 1
            and any(candidate != filename_id_sets[0] for candidate in filename_id_sets[1:])
        ):
            return [
                MatchResult(
                    None,
                    0.0,
                    "needs_review",
                    "Filename evidence is ambiguous or contradictory; manual review is required",
                )
            ]
        if filename_match_groups:
            # The category order encodes the public precedence: passport,
            # exact name, then stored staff/agent/custom identifier.
            return filename_match_groups[0]

        content_match_groups: list[list[MatchResult]] = []
        content_ambiguities: list[MatchResult] = []
        content_passport_values = self._content_passport_values(document)
        passport_matches, ambiguity = self._resolve_uuid_values(
            content_passport_values,
            prepared.passports,
            confidence=0.98,
            reason="PDF text Passport number uniquely matched",
            ambiguity_reason="PDF text passport number matches multiple passengers",
        )
        if ambiguity is not None:
            content_ambiguities.append(ambiguity)
        if passport_matches:
            content_match_groups.append(passport_matches)

        content_words = self._name_words(document.text)
        extracted_name_words = self._name_words(document.extracted_name or "")
        if extracted_name_words:
            name_matches, ambiguity = self._resolve_name_windows(
                extracted_name_words,
                prepared,
                confidence=0.96,
                reason="Extracted passenger name uniquely matched",
                ambiguity_reason="Extracted passenger name matches multiple passengers",
                exact_only=True,
            )
            if ambiguity is not None:
                content_ambiguities.append(ambiguity)
            if name_matches:
                content_match_groups.append(name_matches)

        name_matches, ambiguity = self._resolve_name_windows(
            content_words,
            prepared,
            confidence=0.94,
            reason="PDF text exact passenger name uniquely matched",
            ambiguity_reason="PDF text passenger name matches multiple passengers",
        )
        if ambiguity is not None:
            content_ambiguities.append(ambiguity)
        if name_matches:
            content_match_groups.append(name_matches)

        content_identifier_values = self._content_labeled_identifier_values(document.text)
        identifier_matches, ambiguity = self._resolve_identifier_values(
            content_identifier_values,
            prepared.identifiers,
            confidence=0.89,
            prefix="PDF text",
        )
        if ambiguity is not None:
            content_ambiguities.append(ambiguity)
        if identifier_matches:
            content_match_groups.append(identifier_matches)

        if content_ambiguities:
            return [
                MatchResult(
                    None,
                    0.0,
                    "needs_review",
                    "PDF identity evidence is ambiguous; manual review is required",
                )
            ]
        if content_match_groups:
            matches_by_passenger: dict[uuid.UUID, MatchResult] = {}
            evidence_sets: list[set[uuid.UUID]] = []
            for matches in content_match_groups:
                evidence_set = {
                    match.passenger_id for match in matches if match.passenger_id is not None
                }
                if evidence_set:
                    evidence_sets.append(evidence_set)
                for match in matches:
                    if match.passenger_id is None:
                        continue
                    current = matches_by_passenger.get(match.passenger_id)
                    if current is None or match.confidence > current.confidence:
                        matches_by_passenger[match.passenger_id] = match

            if len(matches_by_passenger) == 1:
                return list(matches_by_passenger.values())

            # A combined PDF is safe to auto-assign only when every independent
            # evidence category agrees with one coherent passenger set.  A
            # singleton (for example a cover-page name) may narrow that set,
            # but it must never add a third passenger to passports that identify
            # two different people.  Picking the largest set and requiring all
            # other sets to be subsets also rejects overlapping contradictions
            # such as {A, B} versus {B, C}.
            # Evidence groups are appended in trust order (passport, extracted
            # name, exact text name, then stored identifiers).  Lower-priority
            # evidence may narrow the first group, but must never expand it.
            # This also prevents a list of extra names from piggybacking on one
            # or more authoritative passport matches.
            dominant_evidence_set = evidence_sets[0] if len(evidence_sets[0]) > 1 else None
            evidence_is_consistent = dominant_evidence_set is not None and all(
                evidence_set.issubset(dominant_evidence_set) for evidence_set in evidence_sets
            )
            if evidence_is_consistent:
                assert dominant_evidence_set is not None
                return [
                    MatchResult(
                        passenger_id,
                        matches_by_passenger[passenger_id].confidence,
                        "matched",
                        "PDF contains multiple uniquely identified passengers",
                    )
                    for passenger_id in sorted(dominant_evidence_set, key=str)
                ]
            return [
                MatchResult(
                    None,
                    0.0,
                    "needs_review",
                    "PDF identity evidence points to different passengers; manual review is required",
                )
            ]

        fuzzy = self._bounded_fuzzy_name_match(content_words, prepared)
        if fuzzy is not None:
            return [fuzzy]
        return [MatchResult(None, 0.0, "needs_review", "No passenger match found")]

    def mark_duplicates(self, matches: list[MatchResult]) -> list[MatchResult]:
        best_by_passenger: dict[uuid.UUID, int] = {}
        for index, match in enumerate(matches):
            if not match.passenger_id:
                continue
            best_index = best_by_passenger.get(match.passenger_id)
            if best_index is None or match.confidence > matches[best_index].confidence:
                best_by_passenger[match.passenger_id] = index

        deduped: list[MatchResult] = []
        for index, match in enumerate(matches):
            if match.passenger_id and best_by_passenger.get(match.passenger_id) != index:
                deduped.append(
                    MatchResult(
                        match.passenger_id,
                        match.confidence,
                        "duplicate_document",
                        "Another uploaded file matched this passenger better",
                    )
                )
            else:
                deduped.append(match)
        return deduped

    def _pdf_text(self, content: bytes) -> str:
        text = self._extract_pdf_text_with_pypdf(content)
        if text:
            return text
        return self._extract_image_only_pdf_text(content)

    def _extract_image_only_pdf_text(self, content: bytes) -> str:
        """OCR a bounded image-only PDF after repeating all active-content checks."""

        if PdfReader is None or pypdfium2 is None or len(content) > MAX_PDF_SOURCE_BYTES:
            return ""
        started_at = time.monotonic()
        try:
            reader = PdfReader(BytesIO(content), strict=False)
            if reader.is_encrypted or not reader.pages or len(reader.pages) > MAX_PDF_TOTAL_PAGES:
                return ""
            if self._has_active_pdf_features(
                reader,
                deadline=started_at + MAX_PDF_PARSE_SECONDS,
            ):
                return ""

            import pytesseract

            document = pypdfium2.PdfDocument(content)
            page_texts: list[str] = []
            text_length = 0
            page_count = min(len(document), MAX_PDF_OCR_PAGES)
            for page_index in range(page_count):
                remaining_seconds = MAX_PDF_PARSE_SECONDS - (time.monotonic() - started_at)
                if remaining_seconds <= 0.25:
                    break
                page = document[page_index]
                bitmap = page.render(scale=PDF_OCR_RENDER_SCALE)
                image = bitmap.to_pil()
                if image.width * image.height > MAX_PDF_OCR_PIXELS:
                    image.thumbnail((2000, 2000))
                try:
                    page_text = pytesseract.image_to_string(
                        image,
                        lang="eng",
                        config="--oem 1 --psm 6",
                        timeout=max(0.25, remaining_seconds),
                    )
                except RuntimeError:
                    if page_texts:
                        break
                    raise
                normalized = "\n".join(
                    " ".join(line.split()) for line in page_text.splitlines() if line.strip()
                )
                remaining_chars = MAX_PDF_TEXT_CHARS - text_length
                if remaining_chars <= 0:
                    break
                page_texts.append(normalized[:remaining_chars])
                text_length += min(len(normalized), remaining_chars)
            return "\n".join(page_texts)[:MAX_PDF_TEXT_CHARS]
        except Exception:
            # Rendering and OCR remain an optional, fail-closed fallback. The
            # isolated parser process owns the hard wall-time and memory caps.
            return ""

    def _extract_pdf_text_with_pypdf(self, content: bytes) -> str:
        if PdfReader is None or len(content) > MAX_PDF_SOURCE_BYTES:
            return ""
        try:
            started_at = time.monotonic()
            reader = PdfReader(BytesIO(content), strict=False)
            if reader.is_encrypted or len(reader.pages) > MAX_PDF_TOTAL_PAGES:
                return ""
            if self._has_active_pdf_features(
                reader,
                deadline=started_at + MAX_PDF_PARSE_SECONDS,
            ):
                return ""
            page_texts: list[str] = []
            text_length = 0
            for page in reader.pages[:MAX_PDF_PAGES_TO_INSPECT]:
                if time.monotonic() - started_at > MAX_PDF_PARSE_SECONDS:
                    return ""
                page_text = (page.extract_text() or "")[:MAX_PDF_PAGE_TEXT_CHARS]
                if time.monotonic() - started_at > MAX_PDF_PARSE_SECONDS:
                    return ""
                if not page_text:
                    continue
                normalized_lines = [
                    " ".join(line.split()) for line in page_text.splitlines() if line.strip()
                ]
                normalized = "\n".join(normalized_lines)
                remaining = MAX_PDF_TEXT_CHARS - text_length
                if remaining <= 0:
                    break
                page_texts.append(normalized[:remaining])
                text_length += min(len(normalized), remaining)
            return "\n".join(page_texts)[:MAX_PDF_TEXT_CHARS]
        except Exception:
            # A malformed, encrypted, image-only, or otherwise unreadable PDF
            # is uncertain and must fail closed instead of being classified by
            # filename or by arbitrary bytes from a compressed stream.
            return ""

    def _has_active_pdf_features(
        self,
        reader: Any,
        *,
        deadline: float | None = None,
    ) -> bool:
        """Reject executable, auto-action, attachment, and XFA PDF features."""

        root = self._resolved_pdf_object(reader.root_object)
        if not isinstance(root, Mapping):
            return True
        if any(
            key in root
            for key in (
                "/OpenAction",
                "/AA",
                "/AF",
                "/Collection",
                "/JavaScript",
                "/JS",
            )
        ):
            return True

        names = self._resolved_pdf_object(root.get("/Names"))
        if isinstance(names, Mapping) and any(
            key in names for key in ("/JavaScript", "/JS", "/EmbeddedFiles")
        ):
            return True

        acro_form = self._resolved_pdf_object(root.get("/AcroForm"))
        if isinstance(acro_form, Mapping):
            if "/XFA" in acro_form or "/AA" in acro_form:
                return True
            if self._pdf_fields_have_actions(
                acro_form.get("/Fields"),
                deadline=deadline,
            ):
                return True

        for page in reader.pages:
            if deadline is not None and time.monotonic() > deadline:
                return True
            page_object = self._resolved_pdf_object(page)
            if not isinstance(page_object, Mapping):
                return True
            if "/AA" in page_object or "/AF" in page_object:
                return True
            annotations = self._resolved_pdf_object(page_object.get("/Annots"))
            if annotations is None:
                continue
            if not isinstance(annotations, (list, tuple)):
                return True
            for annotation_reference in annotations:
                annotation = self._resolved_pdf_object(annotation_reference)
                if not isinstance(annotation, Mapping):
                    return True
                if str(annotation.get("/Subtype", "")) in {
                    "/FileAttachment",
                    "/RichMedia",
                }:
                    return True
                if "/AA" in annotation or self._pdf_action_is_active(
                    annotation.get("/A"),
                    deadline=deadline,
                ):
                    return True
        return False

    def _pdf_fields_have_actions(
        self,
        fields_reference: Any,
        *,
        deadline: float | None,
    ) -> bool:
        fields = self._resolved_pdf_object(fields_reference)
        if fields is None:
            return False
        if not isinstance(fields, (list, tuple)):
            return True
        stack = list(fields)
        visited = 0
        while stack:
            visited += 1
            if visited > 10_000 or (deadline is not None and time.monotonic() > deadline):
                return True
            field = self._resolved_pdf_object(stack.pop())
            if not isinstance(field, Mapping):
                return True
            if "/AA" in field or self._pdf_action_is_active(
                field.get("/A"),
                deadline=deadline,
            ):
                return True
            children = self._resolved_pdf_object(field.get("/Kids"))
            if children is None:
                continue
            if not isinstance(children, (list, tuple)):
                return True
            stack.extend(children)
        return False

    def _pdf_action_is_active(
        self,
        action_reference: Any,
        *,
        deadline: float | None,
    ) -> bool:
        if action_reference is None:
            return False
        stack = [action_reference]
        visited = 0
        while stack:
            visited += 1
            if visited > 1_000 or (deadline is not None and time.monotonic() > deadline):
                return True
            action = self._resolved_pdf_object(stack.pop())
            if not isinstance(action, Mapping):
                return True
            if "/JS" in action or "/JavaScript" in action or "/Launch" in action:
                return True
            if str(action.get("/S", "")) in {
                "/JavaScript",
                "/Launch",
                "/SubmitForm",
                "/ImportData",
                "/GoToR",
                "/Rendition",
                "/RichMediaExecute",
            }:
                return True
            next_action = self._resolved_pdf_object(action.get("/Next"))
            if next_action is None:
                continue
            if isinstance(next_action, (list, tuple)):
                stack.extend(next_action)
            else:
                stack.append(next_action)
        return False

    def _resolved_pdf_object(self, value: Any) -> Any:
        if value is None:
            return None
        resolver = getattr(value, "get_object", None)
        return resolver() if callable(resolver) else value

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
        ticket_is_conclusive = ticket_core_score >= 1 and ticket_has_structure

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

    def _text_lines(self, text: str) -> list[str]:
        lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
        if not lines and text.strip():
            lines = [" ".join(text.split())]
        return lines[:4_000]

    def _nearby_label_candidates(self, text: str, label_pattern: str) -> list[str]:
        """Return bounded value candidates on either side of nearby labels."""

        label_re = re.compile(
            rf"(?<!\w)(?:{label_pattern})(?!\w)",
            flags=re.IGNORECASE,
        )
        lines = self._text_lines(text)
        candidates: list[str] = []

        def add(candidate: str) -> None:
            bounded = " ".join(candidate.split()).strip(" \t:#–—-")[:180]
            if bounded and bounded not in candidates:
                candidates.append(bounded)

        for index, line in enumerate(lines):
            for label_match in label_re.finditer(line):
                after = line[label_match.end() : label_match.end() + 180].strip()
                if after:
                    # A translated label may sit between the English anchor and
                    # its value: ``Full name / Họ tên: VALUE``.
                    colon = after.find(":")
                    translated_prefix_without_value = (
                        after.lstrip().startswith(("/", "(", "[")) and colon < 0
                    )
                    if translated_prefix_without_value:
                        after = ""
                    elif colon == 0 or (
                        0 < colon <= 80 and after.lstrip().startswith(("/", "(", "["))
                    ):
                        after = after[colon + 1 :]
                    add(after)

                before = line[max(0, label_match.start() - 180) : label_match.start()]
                if ":" in before:
                    before = before.rsplit(":", 1)[1]
                add(before)

                # PDF extractors commonly put a translated label/value on the
                # line immediately before the English label, or the value on
                # the immediately following line.  One-line adjacency is
                # enough for that layout and avoids borrowing distant fields.
                for neighbor_index in (index - 1, index + 1):
                    if not 0 <= neighbor_index < len(lines):
                        continue
                    neighbor = lines[neighbor_index]
                    if ":" in neighbor:
                        neighbor = neighbor.rsplit(":", 1)[1]
                    add(neighbor)
        return candidates

    def _nearby_labeled_values(
        self,
        text: str,
        label_pattern: str,
        value_pattern: str,
    ) -> tuple[str, ...]:
        value_re = re.compile(value_pattern, flags=re.IGNORECASE)
        values: list[str] = []
        for candidate in self._nearby_label_candidates(text, label_pattern):
            for match in value_re.finditer(candidate):
                value = " ".join(match.group(0).split())
                if value not in values:
                    values.append(value)
        return tuple(values)

    def _has_labeled_value(self, text: str, label_pattern: str, value_pattern: str) -> bool:
        return bool(self._nearby_labeled_values(text, label_pattern, value_pattern))

    def _term_score(self, normalized_text: str, terms: tuple[str, ...]) -> int:
        padded_text = f" {normalized_text} "
        normalized_terms = {self._normalize(term) for term in terms}
        return sum(1 for term in normalized_terms if f" {term} " in padded_text)

    def _extract_labeled_name(self, text: str) -> str | None:
        label_pattern = (
            r"(?:full\s+name|name\s+of\s+(?:applicant|holder)|applicant\s+name|"
            r"visa\s+holder(?:'s)?\s+name|passenger\s+name|họ\s+(?:và\s+)?tên|"
            r"nom\s+complet|nombre\s+completo|nome\s+completo|vollständiger\s+name)"
        )
        for candidate in self._nearby_label_candidates(text, label_pattern):
            if any(character.isdigit() for character in candidate):
                continue
            cleaned = self._clean_person_name(candidate, "visa")
            letters = sum(character.isalpha() for character in cleaned)
            words = re.findall(r"[^\W\d_]+", cleaned, flags=re.UNICODE)
            if letters >= 3 and 1 <= len(words) <= MAX_NAME_TOKENS:
                return cleaned[:255]
        return None

    def _extract_visa_reference(self, text: str) -> str | None:
        label_pattern = (
            r"(?:e-?visa\s+(?:number|no|n[o0º°])|electronic\s+visa\s+(?:number|no)|"
            r"visa\s+(?:number|no|n[o0º°]|reference|code)|grant\s+number|"
            r"entry\s+permit\s+number|"
            r"document\s+(?:reference|number)|reference\s+(?:no|number)|"
            r"(?<!\w\s)(?:n[o0º°]|code))"
        )
        token_re = re.compile(
            r"(?<!\w)[A-Z0-9](?:[A-Z0-9./-]{4,31})(?!\w)",
            flags=re.IGNORECASE,
        )
        for candidate in self._nearby_label_candidates(text, label_pattern):
            for match in token_re.finditer(candidate):
                raw = match.group(0)
                if re.fullmatch(r"\d{1,4}[./-]\d{1,2}[./-]\d{1,4}", raw):
                    continue
                normalized = self._normalize_identifier(raw)
                if (
                    normalized
                    and len(normalized) >= 5
                    and any(character.isdigit() for character in normalized)
                ):
                    return normalized
        return None

    def _extract_visa_dates(self, text: str) -> tuple[str, ...]:
        label_pattern = (
            r"(?:good\s+for\s+entry\s+valid\s+from|valid\s+from|valid\s+until|until|"
            r"date\s+of\s+(?:issue|expiry)|có\s+giá\s+trị\s+từ\s+ngày|đến\s+ngày|"
            r"thời\s+hạn\s+đến)"
        )
        return self._nearby_labeled_values(text, label_pattern, _DATE_VALUE_PATTERN)[:6]

    def _extract_name(self, text: str, detected_type: str) -> str | None:
        labeled_name = self._extract_labeled_name(text)
        if labeled_name:
            return labeled_name
        if detected_type == "flight_ticket":
            slash_name = self._extract_slash_ticket_name(text)
            if slash_name:
                return slash_name
        patterns: tuple[str, ...]
        if detected_type == "visa":
            patterns = (
                r"\b([A-Z][A-Z ]{3,80})\s*Full\s+Name\s*:",
                r"\b([A-Z][A-Z ]{3,80})\s+\d{4}/\d{2}/\d{2}\s*Date\s+of\s+Arrival\s*:\s*Name\s*:",
                r"(?:full\s+name|name\s+of\s+applicant|name)\s*[:\-]\s*([A-Z][A-Z .]{3,80})",
            )
        elif detected_type == "flight_ticket":
            patterns = (
                r"Passenger\s+Information\s+(?:MR|MRS|MS|MISS)\.?\s+([A-Z][A-Z .]{3,100}?)(?:\s+Adult|\s+Child|\s+Infant|\s+Sector|\s+Seat|\s+DEL|\s+BOM|\s+BLR|\s+HYD|\s+PNR)",
                r"\b(?:MR|MRS|MS|MISS)\.?\s+([A-Z][A-Z .]{3,100}?)(?:\s+Adult|\s+Child|\s+Infant|\s+Sector|\s+Seat)",
                r"(?:passenger\s+name|passenger)\s*[:\-]\s*([A-Z][A-Z .]{3,80})",
            )
        else:
            patterns = (
                r"(?:passenger\s+name|full\s+name|name)\s*[:\-]\s*([A-Z][A-Z .]{3,80})",
                r"\b(?:mr|mrs|ms|miss)\.?\s+([A-Z][A-Z .]{3,80})",
            )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            cleaned = self._clean_person_name(match.group(1), detected_type)
            if len(cleaned.replace(" ", "")) >= 3:
                return cleaned[:255]
        return None

    def _extract_slash_ticket_name(self, text: str) -> str | None:
        pattern = (
            r"\b([A-Z]{2,})/([A-Z][A-Z ]{3,140}?)(?:\s+(?:MR|MRS|MS|MISS)\b|\s+FLIGHT|\s+DATE|\n)"
        )
        candidates: list[tuple[int, str]] = []
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            raw_given = match.group(2)
            surname = self._clean_person_name(match.group(1), "flight_ticket")
            given = self._clean_person_name(raw_given, "flight_ticket")
            combined = " ".join(part for part in (given, surname) if part)
            if len(combined.replace(" ", "")) >= 3:
                score = raw_given.count(" ")
                if not re.search(r"(?:MR|MRS|MS|MISS)$", raw_given.strip(), flags=re.IGNORECASE):
                    score += 2
                candidates.append((score, combined[:255]))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    def _clean_person_name(self, raw_name: str, detected_type: str) -> str:
        name = unicodedata.normalize("NFKC", raw_name).replace("\n", " ")
        stop_pattern = (
            r"\b(?:adult|child|infant|sector|seat|add[- ]?ons|departing|confirmed|payment|"
            r"status|complete|passport|nationality|citizenship|date|birth|gender|male|"
            r"female|visa|ticket|pnr|booking|flight|full\s+name|name\s+of\s+applicant|"
            r"ngày|số\s+hộ\s+chiếu|thời\s+hạn)\b"
        )
        name = re.split(stop_pattern, name, flags=re.IGNORECASE)[0]
        name = re.sub(r"\b(?:mr|mrs|ms|miss)\.?\b", " ", name, flags=re.IGNORECASE)
        name = "".join(
            character
            if (
                character.isalpha()
                or unicodedata.category(character).startswith("M")
                or character in " '-."
            )
            else " "
            for character in name
        )
        name = re.sub(
            r"\b(?:personal|passenger)\s+information\b",
            " ",
            name,
            flags=re.IGNORECASE,
        )
        tokens = [token.upper() for token in name.split() if token]
        noise = {"MALE", "FEMALE", "GENDER", "MALEGENDER", "FEMALEGENDER", "ADULT"}
        tokens = [token for token in tokens if token not in noise]
        if detected_type == "flight_ticket":
            tokens = self._merge_split_name_tokens(tokens)
        cleaned_tokens = [token.capitalize() for token in tokens if len(token) > 1]
        return " ".join(cleaned_tokens)

    def _merge_split_name_tokens(self, tokens: list[str]) -> list[str]:
        merged: list[str] = []
        for token in tokens:
            if merged and (len(token) == 1 or (len(token) == 2 and len(merged[-1]) >= 3)):
                merged[-1] = f"{merged[-1]}{token}"
                continue
            merged.append(token)
        return merged

    def _extract_passport_number(self, text: str) -> str | None:
        label_pattern = (
            r"(?:passport|travel\s+document)(?:\s+(?:no|num|number))?|"
            r"số\s+hộ\s+chiếu|numéro\s+de\s+passeport|número\s+de\s+pasaporte"
        )
        token_re = re.compile(
            r"(?<!\w)(?:[A-Z]{1,3}[\s-]?\d{5,10}[A-Z]?|\d{6,12})(?!\w)",
            flags=re.IGNORECASE,
        )
        for candidate in self._nearby_label_candidates(text, label_pattern):
            for match in token_re.finditer(candidate):
                if normalized := self._normalize_identifier(match.group(0)):
                    return normalized

        match = re.search(
            r"\b([A-Z]{1,2}[\s-]?[0-9]{6,8})\b",
            text.upper(),
        )
        return self._normalize_identifier(match.group(1)) if match else None

    def _extract_reference(self, text: str) -> str | None:
        match = re.search(
            r"\b(?:PNR|BOOKING(?:\s+(?:NO|NUMBER|REF|REFERENCE))?)\s*[:#\-]?\s*([A-Z0-9]{5,10})\b",
            text.upper(),
        )
        if match:
            return match.group(1)
        return self._extract_visa_reference(text)

    def _passport_fields(self, passenger: PassportSubmission) -> dict[str, Any]:
        fields = dict(passenger.extracted_fields or {})
        fields.update(passenger.confirmed_fields or {})
        return fields

    def _normalized_passenger_names(
        self,
        passenger: PassportSubmission,
        fields: Mapping[str, Any],
    ) -> tuple[tuple[str, ...], ...]:
        candidates: list[Any] = [passenger.client_name]
        candidates.extend(self._mapping_values(fields, _FULL_NAME_KEYS))
        given_values = self._mapping_values(fields, _GIVEN_NAME_KEYS) or [""]
        surname_values = self._mapping_values(fields, _SURNAME_KEYS) or [""]
        for given in given_values:
            for surname in surname_values:
                given_text = str(given or "").strip()
                surname_text = str(surname or "").strip()
                candidates.extend(
                    [
                        " ".join(part for part in (given_text, surname_text) if part),
                        " ".join(part for part in (surname_text, given_text) if part),
                    ]
                )

        names: list[tuple[str, ...]] = []
        seen: set[tuple[str, ...]] = set()
        for candidate in candidates:
            tokens = tuple(self._name_words(str(candidate or ""))[:MAX_NAME_TOKENS])
            if not tokens or tokens in seen:
                continue
            seen.add(tokens)
            names.append(tokens)
            if len(names) >= MAX_PASSENGER_NAMES:
                break
        return tuple(names)

    def _identifier_aliases(self, mapping: Mapping[str, Any]) -> list[tuple[str, str]]:
        aliases: list[tuple[str, str]] = []
        normalized_mapping = {self._normalize_key(key): value for key, value in mapping.items()}
        person_type = normalized_mapping.get("agent_employee_type")
        for raw_key, raw_value in list(mapping.items())[:MAX_PASSENGER_IDENTIFIERS]:
            key = self._normalize_key(raw_key)
            if not self._is_identifier_key(key):
                continue
            value = self._normalize_identifier(raw_value)
            if not value or not any(character.isdigit() for character in value):
                continue
            kind = self._identifier_kind(key)
            aliases.append((value, kind))
            if key in _STAFF_CODE_KEYS:
                if prefixed := prefixed_staff_code(raw_value):
                    if normalized_prefixed := self._normalize_identifier(prefixed):
                        aliases.append((normalized_prefixed, "staff code"))
            if key in _AGENT_CODE_KEYS:
                prefixed = prefixed_agent_employee_code(person_type, raw_value)
                if prefixed and (normalized_prefixed := self._normalize_identifier(prefixed)):
                    aliases.append((normalized_prefixed, "agent or employee code"))
        return list(dict.fromkeys(aliases))[:MAX_PASSENGER_IDENTIFIERS]

    def _mapping_values(
        self,
        mapping: Mapping[str, Any],
        keys: frozenset[str],
    ) -> list[Any]:
        values: list[Any] = []
        for raw_key, value in mapping.items():
            normalized = self._normalize_key(raw_key)
            base_key = re.sub(r"_\d+$", "", normalized)
            if normalized in keys or base_key in keys:
                values.append(value)
        return values

    def _resolve_uuid_values(
        self,
        values: set[str],
        owners_by_value: Mapping[str, tuple[uuid.UUID, ...]],
        *,
        confidence: float,
        reason: str,
        ambiguity_reason: str,
    ) -> tuple[list[MatchResult], MatchResult | None]:
        matched_ids: set[uuid.UUID] = set()
        ambiguous = False
        for value in values:
            owners = owners_by_value.get(value, ())
            if len(owners) == 1:
                matched_ids.add(owners[0])
            elif len(owners) > 1:
                ambiguous = True
        matches = [
            MatchResult(passenger_id, confidence, "matched", reason)
            for passenger_id in sorted(matched_ids, key=str)
        ]
        if ambiguous:
            return matches, MatchResult(
                None,
                0.0,
                "needs_review",
                f"{ambiguity_reason}; manual review is required",
            )
        return matches, None

    def _resolve_name_windows(
        self,
        words: list[str],
        index: DocumentMatchIndex,
        *,
        confidence: float,
        reason: str,
        ambiguity_reason: str,
        exact_only: bool = False,
    ) -> tuple[list[MatchResult], MatchResult | None]:
        if not words:
            return [], None
        values: set[tuple[str, ...]] = set()
        lengths = index.name_lengths
        if exact_only:
            exact = tuple(words[:MAX_NAME_TOKENS])
            if exact in index.names:
                values.add(exact)
        else:
            for length in lengths:
                if length > len(words):
                    continue
                if length == 1 and len(words) != 1:
                    continue
                for start in range(0, len(words) - length + 1):
                    candidate = tuple(words[start : start + length])
                    if candidate in index.names:
                        values.add(candidate)

        matched_ids: set[uuid.UUID] = set()
        ambiguous = False
        for value in values:
            owners = index.names.get(value, ())
            if len(owners) == 1:
                matched_ids.add(owners[0])
            elif len(owners) > 1:
                ambiguous = True
        matches = [
            MatchResult(passenger_id, confidence, "matched", reason)
            for passenger_id in sorted(matched_ids, key=str)
        ]
        if ambiguous:
            return matches, MatchResult(
                None,
                0.0,
                "needs_review",
                f"{ambiguity_reason}; manual review is required",
            )
        return matches, None

    def _resolve_identifier_values(
        self,
        values: set[str],
        owners_by_value: Mapping[str, tuple[_IdentifierOwner, ...]],
        *,
        confidence: float,
        prefix: str,
    ) -> tuple[list[MatchResult], MatchResult | None]:
        unique_by_passenger: dict[uuid.UUID, _IdentifierOwner] = {}
        ambiguous_kinds: set[str] = set()
        for value in values:
            owners = owners_by_value.get(value, ())
            passenger_ids = {owner.passenger_id for owner in owners}
            if len(passenger_ids) == 1 and owners:
                owner = owners[0]
                unique_by_passenger.setdefault(owner.passenger_id, owner)
            elif len(passenger_ids) > 1:
                ambiguous_kinds.update(owner.kind for owner in owners)

        matches = [
            MatchResult(
                passenger_id,
                confidence,
                "matched",
                f"{prefix} {owner.kind} uniquely matched from {owner.source}",
            )
            for passenger_id, owner in sorted(
                unique_by_passenger.items(),
                key=lambda item: str(item[0]),
            )
        ]
        if ambiguous_kinds:
            kinds = ", ".join(sorted(ambiguous_kinds))
            return matches, MatchResult(
                None,
                0.0,
                "needs_review",
                f"{prefix} {kinds} matches multiple passengers; manual review is required",
            )
        return matches, None

    def _bounded_fuzzy_name_match(
        self,
        words: list[str],
        index: DocumentMatchIndex,
    ) -> MatchResult | None:
        document_tokens = {
            token for token in words if len(token) > 1 and token not in _NAME_NOISE_TOKENS
        }
        if not document_tokens:
            return None

        hit_counts: dict[uuid.UUID, int] = defaultdict(int)
        for token in document_tokens:
            owners = index.name_token_passengers.get(token, ())
            # Extremely common name tokens add CPU but no useful discrimination.
            if len(owners) > 64:
                continue
            for passenger_id in owners:
                hit_counts[passenger_id] += 1
        if not hit_counts:
            return None

        candidate_ids = sorted(hit_counts, key=lambda item: (-hit_counts[item], str(item)))[
            :MAX_FUZZY_CANDIDATES
        ]
        scores: list[tuple[float, uuid.UUID]] = []
        for passenger_id in candidate_ids:
            profile = index.profiles_by_id[passenger_id]
            best = 0.0
            for name in profile.names:
                meaningful = {
                    token for token in name if len(token) > 1 and token not in _NAME_NOISE_TOKENS
                }
                if len(meaningful) < 2:
                    continue
                coverage = len(meaningful & document_tokens) / len(meaningful)
                best = max(best, coverage * 0.86)
            if best:
                scores.append((best, passenger_id))
        if not scores:
            return None
        scores.sort(key=lambda item: (-item[0], str(item[1])))
        best_score, best_id = scores[0]
        second_score = scores[1][0] if len(scores) > 1 else 0.0
        if best_score >= 0.82 and best_score - second_score >= 0.15:
            return MatchResult(
                best_id,
                best_score,
                "matched",
                "PDF text passenger-name tokens uniquely matched",
            )
        if best_score >= 0.62:
            return MatchResult(
                None,
                best_score,
                "needs_review",
                "Passenger-name evidence is incomplete or ambiguous; manual review is required",
            )
        return None

    def _filename_identifier_values(self, filename_stem: str) -> set[str]:
        tokens = [token.upper() for token in re.findall(r"[A-Za-z0-9]+", filename_stem)]
        values: set[str] = set()
        for index, token in enumerate(tokens[:24]):
            if any(character.isdigit() for character in token):
                values.add(token)
            for width in (2, 3):
                parts = tokens[index : index + width]
                if len(parts) != width:
                    continue
                joined = "".join(parts)
                if len(joined) <= 64 and any(character.isdigit() for character in joined):
                    values.add(joined)
        meaningful = [token for token in tokens if token.casefold() not in _DOCUMENT_FILENAME_WORDS]
        compact = "".join(meaningful)
        if compact and len(compact) <= 64 and any(character.isdigit() for character in compact):
            values.add(compact)
        return {value for value in values if 1 <= len(value) <= 64}

    def _content_passport_values(self, document: ClassifiedDocument) -> set[str]:
        values: set[str] = set()
        if document.extracted_passport_number:
            values.add(self._normalize_identifier(document.extracted_passport_number) or "")
        for match in re.finditer(
            r"\b[A-Z]{1,2}[\s-]?[0-9]{6,8}\b",
            document.text.upper(),
        ):
            if value := self._normalize_identifier(match.group(0)):
                values.add(value)
        for match in re.finditer(
            r"\b(?:PASSPORT|TRAVEL\s+DOCUMENT)(?:\s+(?:NO|NUM|NUMBER))?\s*[:#\-]?\s*([A-Z0-9][A-Z0-9\s-]{2,20})",
            document.text.upper(),
        ):
            candidate = match.group(1).split()[0]
            if value := self._normalize_identifier(candidate):
                values.add(value)
        values.discard("")
        return values

    def _content_labeled_identifier_values(self, text: str) -> set[str]:
        values: set[str] = set()
        pattern = re.compile(
            r"\b(?:STAFF|EMPLOYEE|AGENT|PERSONNEL)(?:\s+(?:CODE|ID|NO|NUMBER))"
            r"\s*[:#\-]?\s*([A-Z0-9][A-Z0-9_-]{0,63})\b",
            flags=re.IGNORECASE,
        )
        for match in pattern.finditer(text[:MAX_PDF_TEXT_CHARS]):
            if value := self._normalize_identifier(match.group(1)):
                values.add(value)
        return values

    def _name_words(self, value: str) -> list[str]:
        compatible = unicodedata.normalize("NFKC", value).casefold()
        return re.findall(r"[^\W_]+", compatible, flags=re.UNICODE)[:40_000]

    def _normalize_identifier(self, value: object) -> str | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        raw = " ".join(str(value).strip().split())
        if not raw or len(raw) > 80:
            return None
        normalized = re.sub(r"[^A-Z0-9]+", "", raw.upper())
        return normalized if 1 <= len(normalized) <= 64 else None

    def _normalize_key(self, value: object) -> str:
        raw = str(value or "")
        camel_case_split = re.sub(
            r"(?<=[A-Z])(?=[A-Z][a-z])|(?<=[a-z0-9])(?=[A-Z])",
            " ",
            raw,
        )
        return "_".join(re.findall(r"[a-z0-9]+", camel_case_split.casefold()))

    def _is_identifier_key(self, key: str) -> bool:
        if not key or key in _IDENTIFIER_KEY_EXCLUSIONS or key.startswith("source_"):
            return False
        if key in _STAFF_CODE_KEYS or key in _AGENT_CODE_KEYS:
            return True
        tokens = set(key.split("_"))
        return bool(tokens & _IDENTIFIER_KEY_TOKENS)

    def _identifier_kind(self, key: str) -> str:
        if key in _AGENT_CODE_KEYS or "agent" in key:
            return "agent or employee code"
        if key in _STAFF_CODE_KEYS or "staff" in key or "employee" in key:
            return "staff code"
        return "stored identifier"

    def _safe_identifier_kind(self, value: str) -> str:
        normalized = self._normalize_key(value).replace("_", " ")
        return normalized[:40] if normalized else "stored identifier"

    def _safe_identifier_source(self, value: str) -> str:
        normalized = " ".join(re.findall(r"[A-Za-z0-9]+", str(value)))
        return normalized[:40] if normalized else "linked group data"

    def _freeze_uuid_index(
        self,
        index: Mapping[str, set[uuid.UUID]],
    ) -> dict[str, tuple[uuid.UUID, ...]]:
        return {value: tuple(sorted(owners, key=str)) for value, owners in index.items()}

    def _freeze_name_index(
        self,
        index: Mapping[tuple[str, ...], set[uuid.UUID]],
    ) -> dict[tuple[str, ...], tuple[uuid.UUID, ...]]:
        return {value: tuple(sorted(owners, key=str)) for value, owners in index.items()}

    def _normalize(self, value: str) -> str:
        compatible = unicodedata.normalize("NFKC", value).casefold()
        return " ".join(re.findall(r"[^\W_]+", compatible, flags=re.UNICODE))

    def _label(self, value: str) -> str:
        return {"visa": "visa", "flight_ticket": "flight ticket", "passport": "passport"}.get(
            value,
            value,
        )
