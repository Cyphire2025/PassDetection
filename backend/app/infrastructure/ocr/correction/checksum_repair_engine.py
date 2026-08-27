"""ICAO check-digit driven MRZ field repair."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.infrastructure.ocr.correction.character_normalizer import CharacterNormalizer

MRZ_WEIGHTS = (7, 3, 1)
COUNTRY_CODES = ("IND",)


@dataclass(frozen=True)
class FieldRepair:
    value: str
    original: str
    checksum_status: str
    reason: str
    confidence: float
    changed_positions: tuple[int, ...] = field(default_factory=tuple)


class ChecksumRepairEngine:
    """Repairs TD3 line-2 fields only when ICAO checksums validate the result."""

    def __init__(self, normalizer: CharacterNormalizer | None = None) -> None:
        self._normalizer = normalizer or CharacterNormalizer()

    def check_digit(self, value: str) -> str:
        total = 0
        for index, char in enumerate(value):
            if char == "<":
                number = 0
            elif char.isdigit():
                number = int(char)
            elif "A" <= char <= "Z":
                number = ord(char) - 55
            else:
                return "-"
            total += number * MRZ_WEIGHTS[index % len(MRZ_WEIGHTS)]
        return str(total % 10)

    def repair_line2(self, raw_line2: str) -> tuple[str, dict[str, FieldRepair]]:
        line2, ambiguous_line2 = self._select_best_line2(raw_line2)
        chars = list(line2)

        passport = self._repair_checked_field(
            field_name="passport_number",
            value="".join(chars[0:9]),
            check_digit=self._normalizer.digit(chars[9]),
            charset="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<",
            normalize="passport",
        )
        chars[0:9] = passport.value
        chars[9] = self._normalizer.digit(chars[9])

        nationality_original = "".join(chars[10:13])
        nationality = self._repair_country_code(nationality_original)
        chars[10:13] = nationality.value

        birth = self._repair_checked_field(
            field_name="date_of_birth",
            value="".join(chars[13:19]),
            check_digit=self._normalizer.digit(chars[19]),
            charset="0123456789",
            normalize="date",
        )
        chars[13:19] = birth.value
        chars[19] = self._normalizer.digit(chars[19])

        sex_original = chars[20]
        sex_value = self._normalizer.sex(sex_original)
        sex = FieldRepair(
            value=sex_value if sex_value in {"M", "F", "<"} else "<",
            original=sex_original,
            checksum_status="not_applicable",
            reason="field_context_normalized" if sex_value != sex_original else "unchanged",
            confidence=0.95 if sex_value in {"M", "F", "<"} else 0.35,
        )
        chars[20] = sex.value

        expiry = self._repair_checked_field(
            field_name="date_of_expiry",
            value="".join(chars[21:27]),
            check_digit=self._normalizer.digit(chars[27]),
            charset="0123456789",
            normalize="date",
        )
        chars[21:27] = expiry.value
        chars[27] = self._normalizer.digit(chars[27])

        personal = self._repair_checked_field(
            field_name="personal_number",
            value="".join(chars[28:42]),
            check_digit=self._normalizer.digit(chars[42]),
            charset="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<",
            normalize="personal",
            allow_review=True,
        )
        chars[28:42] = personal.value
        chars[42] = self._normalizer.digit(chars[42])

        composite_original = "".join(chars[0:10] + chars[13:20] + chars[21:43])
        composite_status = (
            "pass"
            if self.check_digit(composite_original) == self._normalizer.digit(chars[43])
            else "fail"
        )
        chars[43] = self._normalizer.digit(chars[43])
        provenance = {
            "passport_number": passport,
            "nationality": nationality,
            "date_of_birth": birth,
            "sex": sex,
            "date_of_expiry": expiry,
            "personal_number": personal,
            "composite": FieldRepair(
                value=composite_original,
                original=composite_original,
                checksum_status="review_required" if ambiguous_line2 else composite_status,
                reason="ambiguous_line2_repair" if ambiguous_line2 else "icao_composite_checksum",
                confidence=0.35 if ambiguous_line2 else 1.0 if composite_status == "pass" else 0.35,
            ),
        }
        if ambiguous_line2:
            provenance["passport_number"] = FieldRepair(
                value=passport.value,
                original=passport.original,
                checksum_status="review_required",
                reason="ambiguous_line2_repair",
                confidence=0.35,
                changed_positions=passport.changed_positions,
            )
        return "".join(chars), provenance

    def _repair_checked_field(
        self,
        *,
        field_name: str,
        value: str,
        check_digit: str,
        charset: str,
        normalize: str,
        allow_review: bool = False,
    ) -> FieldRepair:
        original = value
        normalized = self._normalize_field(value, normalize)
        if self.check_digit(normalized) == check_digit:
            return FieldRepair(
                value=normalized,
                original=original,
                checksum_status="pass",
                reason="field_context_normalized" if normalized != original else "unchanged",
                confidence=0.99 if normalized != original else 1.0,
                changed_positions=self._changed_positions(original, normalized),
            )

        for candidate, changed_positions in self._single_character_candidates(normalized, charset, normalize):
            if self.check_digit(candidate) == check_digit:
                return FieldRepair(
                    value=candidate,
                    original=original,
                    checksum_status="pass",
                    reason=f"checksum_repair:{field_name}",
                    confidence=0.94,
                    changed_positions=changed_positions,
                )

        return FieldRepair(
            value=normalized,
            original=original,
            checksum_status="review_required" if allow_review else "fail",
            reason="no_checksum_valid_correction",
            confidence=0.35,
            changed_positions=self._changed_positions(original, normalized),
        )

    def _repair_country_code(self, value: str) -> FieldRepair:
        normalized = self._normalizer.country_code(value)
        for code in COUNTRY_CODES:
            distance = sum(1 for current, expected in zip(normalized, code) if current != expected)
            if normalized == code or distance <= 1:
                return FieldRepair(
                    value=code,
                    original=value,
                    checksum_status="not_applicable",
                    reason="country_code_context" if code != value else "unchanged",
                    confidence=0.98 if distance == 0 else 0.90,
                    changed_positions=self._changed_positions(value, code),
                )
        return FieldRepair(
            value=normalized,
            original=value,
            checksum_status="review_required",
            reason="unknown_country_code",
            confidence=0.4,
            changed_positions=self._changed_positions(value, normalized),
        )

    def _select_best_line2(self, value: str) -> tuple[str, bool]:
        sanitized = self._normalizer.sanitize_mrz_text(value)
        windows = [sanitized[index:index + 44] for index in range(max(1, len(sanitized) - 43))]
        if not windows:
            return "".ljust(44, "<"), False
        candidates = [window.ljust(44, "<")[:44] for window in windows]
        if len(sanitized) == 43:
            charset = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
            likely_missing_positions: tuple[int, ...]
            if self._normalizer.country_code(sanitized[9:12]) in COUNTRY_CODES:
                likely_missing_positions = (0,)
            else:
                likely_missing_positions = (0, 9, 10, 13, 21, 28, 42, 43)
            for index in likely_missing_positions:
                for char in charset:
                    candidates.append((sanitized[:index] + char + sanitized[index:])[:44])
            full_valid = sorted(
                {
                    candidate
                    for candidate in candidates
                    if self._is_full_valid_line2(candidate)
                }
            )
            if len(full_valid) == 1:
                return full_valid[0], False
        scored = [(self._line2_score(candidate), candidate) for candidate in candidates]
        best_score = max(score for score, _ in scored)
        best_candidates = sorted({candidate for score, candidate in scored if score == best_score})
        ambiguous = len(best_candidates) > 1 and len(sanitized) != 44
        return best_candidates[0], ambiguous

    def _is_full_valid_line2(self, line2: str) -> bool:
        normalized = list(line2)
        normalized[10:13] = self._normalizer.country_code("".join(normalized[10:13]))
        for index in list(range(13, 20)) + list(range(21, 28)) + [9, 19, 27, 42, 43]:
            normalized[index] = self._normalizer.digit(normalized[index])
        line = "".join(normalized)
        if line[10:13] not in COUNTRY_CODES or line[20] not in {"M", "F", "<"}:
            return False
        checks = (
            (line[0:9], line[9]),
            (line[13:19], line[19]),
            (line[21:27], line[27]),
            (line[28:42], line[42]),
            (line[0:10] + line[13:20] + line[21:43], line[43]),
        )
        return all(self.check_digit(field) == digit for field, digit in checks)

    def _line2_score(self, line2: str) -> int:
        score = 0
        normalized = list(line2)
        normalized[10:13] = self._normalizer.country_code("".join(normalized[10:13]))
        for index in list(range(13, 20)) + list(range(21, 28)) + [9, 19, 27, 42, 43]:
            normalized[index] = self._normalizer.digit(normalized[index])
        line = "".join(normalized)
        checks = (
            (line[0:9], line[9]),
            (line[13:19], line[19]),
            (line[21:27], line[27]),
            (line[28:42], line[42]),
            (line[0:10] + line[13:20] + line[21:43], line[43]),
        )
        score += sum(10 for field, digit in checks if self.check_digit(field) == digit)
        if line[10:13] in COUNTRY_CODES:
            score += 6
        if line[20] in {"M", "F", "<"}:
            score += 2
        return score

    def _normalize_field(self, value: str, field_type: str) -> str:
        if field_type == "date":
            return self._normalizer.date(value)
        if field_type in {"passport", "personal"}:
            return "".join(self._normalizer.sanitize_mrz_text(value)).ljust(len(value), "<")[: len(value)]
        return value

    def _single_character_candidates(
        self,
        value: str,
        charset: str,
        field_type: str,
    ) -> list[tuple[str, tuple[int, ...]]]:
        candidates: list[tuple[str, tuple[int, ...]]] = []
        for index, char in enumerate(value):
            for replacement in self._replacement_order(char, charset, field_type):
                if replacement == char:
                    continue
                candidate = value[:index] + replacement + value[index + 1:]
                candidates.append((candidate, (index,)))
        return candidates

    def _replacement_order(self, char: str, charset: str, field_type: str) -> tuple[str, ...]:
        replacements: list[str] = []
        if field_type == "date":
            replacements.extend([self._normalizer.digit(char), *"0123456789"])
        else:
            confusion = {
                "0": ("O", "D", "Q"),
                "O": ("0", "D", "Q"),
                "1": ("I", "L"),
                "I": ("1", "L"),
                "L": ("1", "I"),
                "2": ("Z",),
                "Z": ("2",),
                "5": ("S",),
                "S": ("5",),
                "6": ("G", "C"),
                "G": ("6", "C"),
                "C": ("6", "G"),
                "7": ("T",),
                "T": ("7",),
                "8": ("B",),
                "B": ("8",),
            }
            replacements.extend(confusion.get(char, ()))
        replacements.extend(charset)
        return tuple(dict.fromkeys(replacement for replacement in replacements if replacement in charset))

    @staticmethod
    def _changed_positions(original: str, corrected: str) -> tuple[int, ...]:
        return tuple(index for index, pair in enumerate(zip(original, corrected)) if pair[0] != pair[1])
