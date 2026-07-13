"""Fast document classification and passenger matching for distribution uploads."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path

from app.domain.entities.entities import PassportSubmission

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - keeps local tooling usable until deps are installed
    PdfReader = None


DOCUMENT_TYPES = {"visa", "flight_ticket", "other"}

VISA_TERMS = (
    "visa",
    "evisa",
    "e-visa",
    "permit",
    "immigration",
    "entry",
    "valid until",
    "duration of stay",
)

TICKET_TERMS = (
    "ticket",
    "e-ticket",
    "itinerary",
    "pnr",
    "booking reference",
    "flight",
    "airline",
    "departure",
    "arrival",
    "boarding",
)

PASSPORT_TERMS = ("passport", "nationality", "place of birth", "date of expiry")


@dataclass(frozen=True)
class ClassifiedDocument:
    original_filename: str
    detected_type: str
    accepted: bool
    reason: str
    text: str
    extracted_name: str | None
    extracted_passport_number: str | None
    extracted_reference: str | None


@dataclass(frozen=True)
class MatchResult:
    passenger_id: uuid.UUID | None
    confidence: float
    status: str
    reason: str


class DocumentMatcher:
    """Cheap text/filename classifier optimized for bulk uploads."""

    def classify(self, *, filename: str, content: bytes, expected_type: str) -> ClassifiedDocument:
        if expected_type not in DOCUMENT_TYPES:
            raise ValueError("Unsupported document type")
        if not filename.lower().endswith(".pdf") or not content.startswith(b"%PDF"):
            return ClassifiedDocument(filename, "unknown", False, "Only PDF files are accepted", "", None, None, None)

        text = self._pdf_text(filename, content)
        detected_type = self._detect_type(text)
        accepted = expected_type == "other" or detected_type == expected_type
        reason = "Accepted"
        if not accepted:
            if detected_type == "unknown":
                reason = f"Could not verify this PDF as a {self._label(expected_type)}"
            else:
                reason = f"Expected {self._label(expected_type)} but detected {self._label(detected_type)}"

        return ClassifiedDocument(
            original_filename=filename,
            detected_type=detected_type,
            accepted=accepted,
            reason=reason,
            text=text,
            extracted_name=self._extract_name(text, detected_type),
            extracted_passport_number=self._extract_passport_number(text),
            extracted_reference=self._extract_reference(text),
        )

    def match(self, document: ClassifiedDocument, passengers: list[PassportSubmission]) -> MatchResult:
        best_passenger: PassportSubmission | None = None
        best_score = 0.0
        best_reason = "No passenger match found"
        haystack = self._normalize(f"{document.original_filename} {document.text}")

        for passenger in passengers:
            fields = passenger.confirmed_fields or passenger.extracted_fields or {}
            passport_number = str(fields.get("passport_number") or "").strip()
            if passport_number and self._normalize(passport_number) in haystack:
                return MatchResult(passenger.id, 0.98, "matched", "Passport number matched")

            candidate_names = self._candidate_names(passenger)
            for name in candidate_names:
                normalized_name = self._normalize(name)
                if not normalized_name:
                    continue
                name_tokens = [token for token in normalized_name.split() if len(token) > 1]
                token_hits = sum(1 for token in name_tokens if token in haystack)
                token_score = token_hits / max(len(name_tokens), 1)
                sequence_score = SequenceMatcher(None, normalized_name, haystack[: max(len(normalized_name) * 3, 120)]).ratio()
                score = max(token_score * 0.86, sequence_score * 0.72)
                if normalized_name in haystack:
                    score = max(score, 0.9)
                if score > best_score:
                    best_score = score
                    best_passenger = passenger
                    best_reason = f"Name matched: {name}"

        if not best_passenger or best_score < 0.55:
            return MatchResult(None, best_score, "needs_review", best_reason)
        if best_score >= 0.82:
            return MatchResult(best_passenger.id, min(best_score, 0.96), "matched", best_reason)
        return MatchResult(best_passenger.id, best_score, "needs_review", best_reason)

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
                    MatchResult(match.passenger_id, match.confidence, "duplicate_document", "Another uploaded file matched this passenger better")
                )
            else:
                deduped.append(match)
        return deduped

    def _pdf_text(self, filename: str, content: bytes) -> str:
        extracted = self._extract_pdf_text_with_pypdf(content)
        if extracted:
            return f"{Path(filename).stem} {extracted}"[:200_000]
        return self._fast_pdf_text(filename, content)

    def _extract_pdf_text_with_pypdf(self, content: bytes) -> str:
        if PdfReader is None:
            return ""
        try:
            reader = PdfReader(BytesIO(content))
            page_texts: list[str] = []
            for page in reader.pages[:5]:
                page_text = page.extract_text() or ""
                if page_text:
                    page_texts.append(page_text)
            return " ".join(" ".join(page_text.split()) for page_text in page_texts)
        except Exception:
            return ""

    def _fast_pdf_text(self, filename: str, content: bytes) -> str:
        snippet = content[:1_500_000].decode("latin-1", errors="ignore")
        readable = " ".join(re.findall(r"[A-Za-z0-9][A-Za-z0-9 .,:;#/-]{2,}", snippet))
        return f"{Path(filename).stem} {readable}"[:200_000]

    def _detect_type(self, text: str) -> str:
        normalized = self._normalize(text)
        visa_score = sum(1 for term in VISA_TERMS if term in normalized)
        ticket_score = sum(1 for term in TICKET_TERMS if term in normalized)
        passport_score = sum(1 for term in PASSPORT_TERMS if term in normalized)
        if ticket_score >= max(2, visa_score + 1):
            return "flight_ticket"
        if visa_score >= 1 and visa_score >= ticket_score:
            return "visa"
        if passport_score >= 2 and ticket_score == 0 and visa_score == 0:
            return "passport"
        return "unknown"

    def _extract_name(self, text: str, detected_type: str) -> str | None:
        if detected_type == "flight_ticket":
            slash_name = self._extract_slash_ticket_name(text)
            if slash_name:
                return slash_name
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
        pattern = r"\b([A-Z]{2,})/([A-Z][A-Z ]{3,140}?)(?:\s+(?:MR|MRS|MS|MISS)\b|\s+FLIGHT|\s+DATE|\n)"
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
        name = raw_name.replace("\n", " ")
        stop_pattern = (
            r"\b(?:adult|child|infant|sector|seat|add[- ]?ons|departing|confirmed|payment|status|complete|"
            r"passport|nationality|citizenship|date|birth|gender|male|female|visa|ticket|pnr|booking|flight)\b"
        )
        name = re.split(stop_pattern, name, flags=re.IGNORECASE)[0]
        name = re.sub(r"\b(?:mr|mrs|ms|miss)\.?\b", " ", name, flags=re.IGNORECASE)
        name = re.sub(r"[^A-Za-z ]+", " ", name)
        name = re.sub(r"\b(?:personal|passenger)\s+information\b", " ", name, flags=re.IGNORECASE)
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
        match = re.search(r"\b([A-Z][0-9]{7}|[A-Z]{1,2}[0-9]{6,8})\b", text.upper())
        return match.group(1) if match else None

    def _extract_reference(self, text: str) -> str | None:
        match = re.search(r"\b(?:PNR|BOOKING(?:\s+REFERENCE)?)\s*[:\-]?\s*([A-Z0-9]{5,10})\b", text.upper())
        return match.group(1) if match else None

    def _candidate_names(self, passenger: PassportSubmission) -> list[str]:
        fields = passenger.confirmed_fields or passenger.extracted_fields or {}
        names = [passenger.client_name]
        given = str(fields.get("given_names") or "").strip()
        surname = str(fields.get("surname") or "").strip()
        if given or surname:
            names.append(f"{given} {surname}".strip())
        return list(dict.fromkeys(name for name in names if name))

    def _normalize(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def _label(self, value: str) -> str:
        return {"visa": "visa", "flight_ticket": "flight ticket", "passport": "passport"}.get(value, value)
