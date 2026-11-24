"""Request-local batch deduplication and fail-closed parser result admission."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

from app.domain.value_objects.travel_document_taxonomy import classification_document_type
from app.infrastructure.documents.document_matcher_models import (
    ClassifiedDocument as ClassifiedDocument,
)
from app.infrastructure.documents.document_matcher_models import (
    DocumentParserUnavailableError as DocumentParserUnavailableError,
)
from app.infrastructure.documents.document_matcher_models import (
    UnsupportedDocumentBatchFormatError as UnsupportedDocumentBatchFormatError,
)
from app.infrastructure.documents.document_matcher_rules import (
    PDF_OCR_RETRY_REASON as PDF_OCR_RETRY_REASON,
)

if TYPE_CHECKING:
    from app.infrastructure.documents.document_matcher import DocumentMatcher


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

    expected_types = {
        classification_document_type(expected_type) for _filename, _content, expected_type in jobs
    }
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
    matcher_type: type[DocumentMatcher],
    isolate_pdf_parsing: bool,
    batch_timeout_seconds: float | None = None,
    parser_processes: int | None = None,
    reject_common_unsupported_format: bool = False,
) -> list[ClassifiedDocument]:
    """Reuse exact duplicates within one request while preserving every input row.

    There is no process-wide document cache: passenger text leaves scope with
    the request. Filename and expected type remain part of the key so extension
    validation, lane acceptance and subsequent filename matching cannot drift.
    """

    unique_jobs: list[tuple[str, bytes, str]] = []
    positions: list[int] = []
    job_positions: dict[tuple[str, str, bytes], int] = {}
    for filename, content, expected_type in jobs:
        key = (filename, expected_type, hashlib.sha256(content).digest())
        index = job_positions.get(key)
        if index is None:
            index = len(unique_jobs)
            job_positions[key] = index
            unique_jobs.append((filename, content, expected_type))
        positions.append(index)
    unique_results = _classify_unique_documents(
        matcher,
        unique_jobs,
        matcher_type=matcher_type,
        isolate_pdf_parsing=isolate_pdf_parsing,
        batch_timeout_seconds=batch_timeout_seconds,
        parser_processes=parser_processes,
    )
    classifications = [unique_results[index] for index in positions]
    if reject_common_unsupported_format:
        _raise_for_common_unsupported_format(matcher, jobs, classifications)
    return classifications


def _classify_unique_documents(
    matcher: DocumentMatcher,
    jobs: list[tuple[str, bytes, str]],
    *,
    matcher_type: type[DocumentMatcher],
    isolate_pdf_parsing: bool,
    batch_timeout_seconds: float | None = None,
    parser_processes: int | None = None,
    reject_common_unsupported_format: bool = False,
) -> list[ClassifiedDocument]:
    """Classify a request batch, isolating untrusted parsing when requested.

    Test doubles and explicitly overridden parser methods retain the direct path
    so deterministic unit tests do not spawn child processes.  Production route
    instances use the exact matcher class and therefore always take the sandbox.
    """

    use_sandbox = (
        isolate_pdf_parsing
        and type(matcher) is matcher_type
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

    parser_options: dict[str, Any] = {}
    if batch_timeout_seconds is not None:
        parser_options["batch_timeout_seconds"] = batch_timeout_seconds
    if parser_processes is not None:
        parser_options["parser_processes"] = parser_processes
    payloads = classify_pdf_batch_isolated(jobs, **parser_options)
    retryable_reasons = {PDF_OCR_RETRY_REASON}
    if parser_processes is not None:
        retryable_reasons.update({
            "PDF parser capacity is temporarily exhausted",
            "PDF parser service is temporarily unavailable",
        })
    if any(payload.get("reason") in retryable_reasons for payload in payloads):
        # Verification is read-only at this point. Retry the complete immutable
        # chunk instead of rejecting valid PDFs after temporary parser or OCR
        # contention. Callers without an explicit worker override retain their
        # existing capacity-failure behaviour.
        raise DocumentParserUnavailableError(
            "PDF verification is temporarily busy; retry the upload"
        )
    sandbox_classifications: list[ClassifiedDocument] = []
    for (filename, _content, _expected_type), payload in zip(jobs, payloads, strict=True):
        detected_type = payload.get("detected_type")
        accepted = payload.get("accepted")
        reason = payload.get("reason")
        text = payload.get("text")
        extracted_name = payload.get("extracted_name")
        extracted_passport_number = payload.get("extracted_passport_number")
        extracted_reference = payload.get("extracted_reference")
        manual_review_allowed = payload.get("manual_review_allowed", False)
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
            and isinstance(manual_review_allowed, bool)
        )
        if not payload_is_valid:
            sandbox_classifications.append(
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
        sandbox_classifications.append(
            ClassifiedDocument(
                original_filename=filename,
                detected_type=cast(str, detected_type),
                accepted=cast(bool, accepted),
                reason=cast(str, reason),
                text=cast(str, text),
                extracted_name=cast(str | None, extracted_name),
                extracted_passport_number=cast(str | None, extracted_passport_number),
                extracted_reference=cast(str | None, extracted_reference),
                manual_review_allowed=(
                    manual_review_allowed is True and detected_type == "unknown" and not accepted
                ),
            )
        )
    if reject_common_unsupported_format:
        _raise_for_common_unsupported_format(matcher, jobs, sandbox_classifications)
    return sandbox_classifications
