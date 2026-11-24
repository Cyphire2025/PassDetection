"""Shared immutable document-classification and scoped matching records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.entities.entities import PassportSubmission


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
    manual_review_allowed: bool = False

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
    compact_names: dict[str, tuple[uuid.UUID, ...]]
    partial_name_pairs: dict[tuple[str, ...], tuple[uuid.UUID, ...]]
    identifiers: dict[str, tuple[_IdentifierOwner, ...]]
    name_token_passengers: dict[str, tuple[uuid.UUID, ...]]
    name_lengths: tuple[int, ...]

class DocumentParserUnavailableError(RuntimeError):
    """Transient parser-capacity failure that callers should expose as retryable."""

class UnsupportedDocumentBatchFormatError(RuntimeError):
    """A repeated, readable batch layout could not be verified safely."""
