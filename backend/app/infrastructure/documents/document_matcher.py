"""Bounded document classification and deterministic passenger matching."""

from __future__ import annotations

import importlib
import uuid as uuid
from pathlib import Path
from typing import Any

from app.domain.entities.entities import PassportSubmission
from app.domain.value_objects.travel_document_taxonomy import (
    DOCUMENT_TYPES,
    classification_document_type,
)
from app.domain.value_objects.travel_document_taxonomy import (
    SUPPORTED_TRAVEL_DOCUMENT_TYPES as SUPPORTED_TRAVEL_DOCUMENT_TYPES,
)
from app.infrastructure.documents import document_batch_classification as _batch_classification
from app.infrastructure.documents import document_pdf_support as _pdf_support
from app.infrastructure.documents.document_approval_provenance import (
    MANUAL_DOCUMENT_TYPE_APPROVAL_PREFIX,
    has_manual_document_type_approval,
)
from app.infrastructure.documents.document_batch_classification import (
    _raise_for_common_unsupported_format as _raise_for_common_unsupported_format,
)
from app.infrastructure.documents.document_content_matching import (
    collect_primary_content_evidence as _collect_primary_content_evidence,
)
from app.infrastructure.documents.document_content_matching import (
    collect_secondary_content_evidence as _collect_secondary_content_evidence,
)
from app.infrastructure.documents.document_content_matching import (
    merge_manifest_name_matches as _merge_manifest_name_matches,
)
from app.infrastructure.documents.document_filename_matching import (
    match_filename_evidence as _match_filename_evidence,
)
from app.infrastructure.documents.document_identity_limits import DocumentIdentityLimits
from app.infrastructure.documents.document_match_resolution import DocumentMatchResolution
from app.infrastructure.documents.document_match_results import (
    mark_duplicate_matches as _mark_duplicate_matches,
)
from app.infrastructure.documents.document_match_results import (
    resolve_content_evidence as _resolve_content_evidence,
)
from app.infrastructure.documents.document_match_results import (
    select_single_passenger_match as _select_single_passenger_match,
)
from app.infrastructure.documents.document_matcher_models import (
    ClassifiedDocument as ClassifiedDocument,
)
from app.infrastructure.documents.document_matcher_models import (
    DocumentMatchIndex as DocumentMatchIndex,
)
from app.infrastructure.documents.document_matcher_models import (
    DocumentParserUnavailableError as DocumentParserUnavailableError,
)
from app.infrastructure.documents.document_matcher_models import MatchResult as MatchResult
from app.infrastructure.documents.document_matcher_models import (
    PassengerIdentifier as PassengerIdentifier,
)
from app.infrastructure.documents.document_matcher_models import (
    UnsupportedDocumentBatchFormatError as UnsupportedDocumentBatchFormatError,
)
from app.infrastructure.documents.document_matcher_models import (
    _IdentifierOwner as _IdentifierOwner,
)
from app.infrastructure.documents.document_matcher_models import (
    _PassengerProfile as _PassengerProfile,
)
from app.infrastructure.documents.document_matcher_models import (
    _VisaDocumentFacts as _VisaDocumentFacts,
)
from app.infrastructure.documents.document_passenger_index import DocumentPassengerIndex
from app.infrastructure.documents.document_pdf_support import (
    DocumentOcrUnavailableError as DocumentOcrUnavailableError,
)
from app.infrastructure.documents.document_pdf_support import (
    _PdfTextRead,
)
from app.infrastructure.documents.document_type_detection import DocumentTextClassifier

try:
    PdfReader: object | None = getattr(importlib.import_module("pypdf"), "PdfReader")
except ImportError:  # pragma: no cover - keeps local tooling usable until deps are installed
    PdfReader = None

try:
    import pypdfium2
except ImportError:  # pragma: no cover - keeps local tooling usable until deps are installed
    pypdfium2 = None


from app.infrastructure.documents.document_matcher_rules import _AGENT_CODE_KEYS as _AGENT_CODE_KEYS
from app.infrastructure.documents.document_matcher_rules import (
    _DATE_VALUE_PATTERN as _DATE_VALUE_PATTERN,
)
from app.infrastructure.documents.document_matcher_rules import (
    _DOCUMENT_FILENAME_WORDS as _DOCUMENT_FILENAME_WORDS,
)
from app.infrastructure.documents.document_matcher_rules import _FULL_NAME_KEYS as _FULL_NAME_KEYS
from app.infrastructure.documents.document_matcher_rules import _GIVEN_NAME_KEYS as _GIVEN_NAME_KEYS
from app.infrastructure.documents.document_matcher_rules import (
    _IDENTIFIER_KEY_EXCLUSIONS as _IDENTIFIER_KEY_EXCLUSIONS,
)
from app.infrastructure.documents.document_matcher_rules import (
    _IDENTIFIER_KEY_TOKENS as _IDENTIFIER_KEY_TOKENS,
)
from app.infrastructure.documents.document_matcher_rules import (
    _NAME_NOISE_TOKENS as _NAME_NOISE_TOKENS,
)
from app.infrastructure.documents.document_matcher_rules import (
    _NON_TRAVEL_DOCUMENT_PATTERNS as _NON_TRAVEL_DOCUMENT_PATTERNS,
)
from app.infrastructure.documents.document_matcher_rules import _PASSPORT_KEYS as _PASSPORT_KEYS
from app.infrastructure.documents.document_matcher_rules import _STAFF_CODE_KEYS as _STAFF_CODE_KEYS
from app.infrastructure.documents.document_matcher_rules import _SURNAME_KEYS as _SURNAME_KEYS
from app.infrastructure.documents.document_matcher_rules import (
    MAX_FUZZY_CANDIDATES as MAX_FUZZY_CANDIDATES,
)
from app.infrastructure.documents.document_matcher_rules import MAX_NAME_TOKENS as MAX_NAME_TOKENS
from app.infrastructure.documents.document_matcher_rules import (
    MAX_PASSENGER_IDENTIFIERS as MAX_PASSENGER_IDENTIFIERS,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_PASSENGER_NAMES as MAX_PASSENGER_NAMES,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_PDF_OCR_PAGES as MAX_PDF_OCR_PAGES,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_PDF_OCR_PIXELS as MAX_PDF_OCR_PIXELS,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_PDF_OCR_SECONDS as MAX_PDF_OCR_SECONDS,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_PDF_PAGE_TEXT_CHARS as MAX_PDF_PAGE_TEXT_CHARS,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_PDF_PAGES_TO_INSPECT as MAX_PDF_PAGES_TO_INSPECT,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_PDF_PARSE_SECONDS as MAX_PDF_PARSE_SECONDS,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_PDF_SOURCE_BYTES as MAX_PDF_SOURCE_BYTES,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_PDF_TEXT_CHARS as MAX_PDF_TEXT_CHARS,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_PDF_TEXT_LAYER_PAGES as MAX_PDF_TEXT_LAYER_PAGES,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_PDF_TOTAL_PAGES as MAX_PDF_TOTAL_PAGES,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_SUPPLEMENTAL_IDENTIFIER_INPUTS as MAX_SUPPLEMENTAL_IDENTIFIER_INPUTS,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER as MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER,
)
from app.infrastructure.documents.document_matcher_rules import (
    MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST as MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST,
)
from app.infrastructure.documents.document_matcher_rules import PASSPORT_TERMS as PASSPORT_TERMS
from app.infrastructure.documents.document_matcher_rules import PAYMENT_TERMS as PAYMENT_TERMS
from app.infrastructure.documents.document_matcher_rules import (
    PDF_OCR_RENDER_SCALE as PDF_OCR_RENDER_SCALE,
)
from app.infrastructure.documents.document_matcher_rules import (
    PDF_OCR_RETRY_REASON as PDF_OCR_RETRY_REASON,
)
from app.infrastructure.documents.document_matcher_rules import (
    TICKET_BOOKING_TERMS as TICKET_BOOKING_TERMS,
)
from app.infrastructure.documents.document_matcher_rules import (
    TICKET_CORE_TERMS as TICKET_CORE_TERMS,
)
from app.infrastructure.documents.document_matcher_rules import (
    TICKET_FLIGHT_TERMS as TICKET_FLIGHT_TERMS,
)
from app.infrastructure.documents.document_matcher_rules import (
    TICKET_ROUTE_TERMS as TICKET_ROUTE_TERMS,
)
from app.infrastructure.documents.document_matcher_rules import (
    TICKET_TRAVEL_TERMS as TICKET_TRAVEL_TERMS,
)
from app.infrastructure.documents.document_matcher_rules import (
    VISA_APPLICATION_TERMS as VISA_APPLICATION_TERMS,
)
from app.infrastructure.documents.document_matcher_rules import (
    VISA_AUTHORITY_TERMS as VISA_AUTHORITY_TERMS,
)
from app.infrastructure.documents.document_matcher_rules import VISA_CORE_TERMS as VISA_CORE_TERMS
from app.infrastructure.documents.document_matcher_rules import (
    VISA_IDENTITY_TERMS as VISA_IDENTITY_TERMS,
)
from app.infrastructure.documents.document_matcher_rules import (
    VISA_VALIDITY_TERMS as VISA_VALIDITY_TERMS,
)


def _pdf_processing_limits() -> _pdf_support.PdfProcessingLimits:
    """Resolve limits at call time so legacy monkeypatch/config seams remain intact."""

    return _pdf_support.PdfProcessingLimits(
        max_ocr_pages=MAX_PDF_OCR_PAGES,
        max_ocr_pixels=MAX_PDF_OCR_PIXELS,
        max_ocr_seconds=MAX_PDF_OCR_SECONDS,
        max_page_text_chars=MAX_PDF_PAGE_TEXT_CHARS,
        max_pages_to_inspect=MAX_PDF_PAGES_TO_INSPECT,
        max_parse_seconds=MAX_PDF_PARSE_SECONDS,
        max_source_bytes=MAX_PDF_SOURCE_BYTES,
        max_text_chars=MAX_PDF_TEXT_CHARS,
        max_text_layer_pages=MAX_PDF_TEXT_LAYER_PAGES,
        max_total_pages=MAX_PDF_TOTAL_PAGES,
        ocr_render_scale=PDF_OCR_RENDER_SCALE,
    )


def classify_documents_bounded(
    matcher: DocumentMatcher,
    jobs: list[tuple[str, bytes, str]],
    *,
    isolate_pdf_parsing: bool,
    batch_timeout_seconds: float | None = None,
    parser_processes: int | None = None,
    reject_common_unsupported_format: bool = False,
) -> list[ClassifiedDocument]:
    return _batch_classification.classify_documents_bounded(
        matcher, jobs, matcher_type=DocumentMatcher,
        isolate_pdf_parsing=isolate_pdf_parsing,
        batch_timeout_seconds=batch_timeout_seconds,
        parser_processes=parser_processes,
        reject_common_unsupported_format=reject_common_unsupported_format,
    )


def _classify_unique_documents(
    matcher: DocumentMatcher,
    jobs: list[tuple[str, bytes, str]],
    *,
    isolate_pdf_parsing: bool,
    batch_timeout_seconds: float | None = None,
    parser_processes: int | None = None,
    reject_common_unsupported_format: bool = False,
) -> list[ClassifiedDocument]:
    return _batch_classification._classify_unique_documents(
        matcher, jobs, matcher_type=DocumentMatcher,
        isolate_pdf_parsing=isolate_pdf_parsing,
        batch_timeout_seconds=batch_timeout_seconds,
        parser_processes=parser_processes,
        reject_common_unsupported_format=reject_common_unsupported_format,
    )


class DocumentMatcher(DocumentTextClassifier, DocumentPassengerIndex, DocumentMatchResolution):
    """Strict classifier plus deterministic, ambiguity-safe passenger matcher."""

    def _identity_limits(self) -> DocumentIdentityLimits:
        """Resolve the compatibility facade's reviewed bounds at call time."""
        return DocumentIdentityLimits(
            MAX_PASSENGER_IDENTIFIERS,
            MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER,
            MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST,
            MAX_SUPPLEMENTAL_IDENTIFIER_INPUTS,
        )

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
        self._last_pdf_safety_passed = False
        text = self._pdf_text(content)
        visa_facts = self._extract_visa_facts(text)
        detected_type = self._detect_type(text, visa_facts=visa_facts)
        expected_classification = classification_document_type(expected_type)
        accepted = expected_classification == "other" or detected_type == expected_classification
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
            manual_review_allowed=(
                not accepted and detected_type == "unknown" and self._last_pdf_safety_passed
            ),
        )

    def match(
        self,
        document: ClassifiedDocument,
        passengers: list[PassportSubmission],
        *,
        index: DocumentMatchIndex | None = None,
    ) -> MatchResult:
        prepared = index or self.build_index(passengers)
        matches = self.match_all(document, passengers, index=prepared)
        return _select_single_passenger_match(matches)

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
        filename_matches = _match_filename_evidence(
            filename=filename, prepared=prepared, resolver=self
        )
        if filename_matches is not None:
            return filename_matches

        evidence = _collect_primary_content_evidence(
            document=document, prepared=prepared, resolver=self
        )
        name_matches, ambiguity = evidence.name_result
        manually_approved_flight = (
            document.accepted
            and has_manual_document_type_approval(document.reason)
            and classification_document_type(
                document.reason.removeprefix(MANUAL_DOCUMENT_TYPE_APPROVAL_PREFIX)
            ) == "flight_ticket"
        )
        if document.detected_type == "flight_ticket" or manually_approved_flight:
            partial_name_matches = self._resolve_ticket_manifest_partial_names(
                document.text,
                prepared,
            )
            if partial_name_matches:
                name_matches = _merge_manifest_name_matches(name_matches, partial_name_matches)
        _collect_secondary_content_evidence(
            document=document, prepared=prepared, resolver=self, evidence=evidence,
            name_matches=name_matches, ambiguity=ambiguity,
        )
        content_matches = _resolve_content_evidence(
            content_match_groups=evidence.match_groups, content_ambiguities=evidence.ambiguities
        )
        if content_matches is not None:
            return content_matches

        fuzzy = self._bounded_fuzzy_name_match(evidence.words, prepared)
        if fuzzy is not None:
            return [fuzzy]
        return [MatchResult(None, 0.0, "needs_review", "No passenger match found")]

    def mark_duplicates(self, matches: list[MatchResult]) -> list[MatchResult]:
        return _mark_duplicate_matches(matches)

    def _pdf_text(self, content: bytes) -> str:
        read = self._read_pdf_text_with_pypdf(content)
        self._last_pdf_safety_passed = read.safe_for_ocr
        if read.text.strip() or not read.safe_for_ocr:
            return read.text
        return self._ocr_validated_image_only_pdf(content)

    def _extract_image_only_pdf_text(self, content: bytes) -> str:
        """OCR a bounded image-only PDF after repeating all active-content checks."""

        read = self._read_pdf_text_with_pypdf(content)
        if read.text.strip() or not read.safe_for_ocr:
            return ""
        return self._ocr_validated_image_only_pdf(content)

    def _ocr_validated_image_only_pdf(self, content: bytes) -> str:
        return _pdf_support.ocr_validated_image_only_pdf(
            content,
            pdfium=pypdfium2,
            limits=_pdf_processing_limits(),
        )

    def _extract_pdf_text_with_pypdf(self, content: bytes) -> str:
        return self._read_pdf_text_with_pypdf(content).text

    def _read_pdf_text_with_pypdf(self, content: bytes) -> _PdfTextRead:
        return _pdf_support.read_pdf_text_with_pypdf(
            content,
            pdf_reader=PdfReader,
            has_active_pdf_features=self._has_active_pdf_features,
            extract_pdf_text_with_pdfium=self._extract_pdf_text_with_pdfium,
            limits=_pdf_processing_limits(),
        )

    def _extract_pdf_text_with_pdfium(
        self,
        content: bytes,
        *,
        deadline: float,
    ) -> str | None:
        return _pdf_support.extract_pdf_text_with_pdfium(
            content,
            pdfium=pypdfium2,
            deadline=deadline,
            limits=_pdf_processing_limits(),
        )

    def _has_active_pdf_features(
        self,
        reader: Any,
        *,
        deadline: float | None = None,
    ) -> bool:
        return _pdf_support.has_active_pdf_features(
            reader,
            deadline=deadline,
            resolve_object=self._resolved_pdf_object,
            fields_have_actions=self._pdf_fields_have_actions,
            action_is_active=self._pdf_action_is_active,
        )

    def _pdf_fields_have_actions(
        self,
        fields_reference: Any,
        *,
        deadline: float | None,
    ) -> bool:
        return _pdf_support.pdf_fields_have_actions(
            fields_reference,
            deadline=deadline,
            resolve_object=self._resolved_pdf_object,
            action_is_active=self._pdf_action_is_active,
        )

    def _pdf_action_is_active(
        self,
        action_reference: Any,
        *,
        deadline: float | None,
    ) -> bool:
        return _pdf_support.pdf_action_is_active(
            action_reference,
            deadline=deadline,
            resolve_object=self._resolved_pdf_object,
        )

    def _resolved_pdf_object(self, value: Any) -> Any:
        return _pdf_support.resolved_pdf_object(value)
