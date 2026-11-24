"""Focused text fields policy; no parser or I/O side effects."""

from __future__ import annotations

import re
import unicodedata

from app.infrastructure.documents.document_matcher_rules import _DATE_VALUE_PATTERN, MAX_NAME_TOKENS
from app.infrastructure.documents.document_text_normalization import DocumentTextNormalization


class DocumentTextFields(DocumentTextNormalization):
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

        fallback_match = re.search(
            r"\b([A-Z]{1,2}[\s-]?[0-9]{6,8})\b",
            text.upper(),
        )
        return self._normalize_identifier(fallback_match.group(1)) if fallback_match else None

    def _extract_reference(self, text: str) -> str | None:
        match = re.search(
            r"\b(?:PNR|BOOKING(?:\s+(?:NO|NUMBER|REF|REFERENCE))?)\s*[:#\-]?\s*([A-Z0-9]{5,10})\b",
            text.upper(),
        )
        if match:
            return match.group(1)
        return self._extract_visa_reference(text)
