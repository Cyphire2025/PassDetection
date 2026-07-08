"""Deterministic ICAO TD3 MRZ correction engine."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.infrastructure.ocr.correction.character_normalizer import CharacterNormalizer
from app.infrastructure.ocr.correction.checksum_repair_engine import ChecksumRepairEngine
from app.infrastructure.ocr.correction.field_validator import FieldProvenance, FieldValidator
from app.infrastructure.ocr.correction.name_normalizer import NameNormalizer


@dataclass(frozen=True)
class ICAOCorrectionResult:
    raw_text: str
    corrected_mrz: str | None
    line1: str | None
    line2: str | None
    provenance: dict[str, FieldProvenance]
    warnings: list[str]
    duration_ms: float
    checksum_pass_rate: float
    debug: dict[str, Any] = field(default_factory=dict)

    @property
    def review_required(self) -> bool:
        return bool(self.warnings)

    def provenance_dict(self) -> dict[str, dict[str, str | float]]:
        return {field: item.to_dict() for field, item in self.provenance.items()}


class ICAOCorrectionEngine:
    """Runs deterministic post-OCR correction before TD3 parsing."""

    def __init__(
        self,
        *,
        normalizer: CharacterNormalizer | None = None,
        checksum_repair: ChecksumRepairEngine | None = None,
        name_normalizer: NameNormalizer | None = None,
        field_validator: FieldValidator | None = None,
    ) -> None:
        self._normalizer = normalizer or CharacterNormalizer()
        self._checksum_repair = checksum_repair or ChecksumRepairEngine(self._normalizer)
        self._name_normalizer = name_normalizer or NameNormalizer(self._normalizer)
        self._field_validator = field_validator or FieldValidator()

    def correct(self, raw_text: str | None) -> ICAOCorrectionResult:
        started = time.perf_counter()
        raw_text = raw_text or ""
        lines = self._extract_candidate_lines(raw_text)
        if len(lines) < 2:
            return ICAOCorrectionResult(
                raw_text=raw_text,
                corrected_mrz=None,
                line1=None,
                line2=None,
                provenance={},
                warnings=["review_required:no_two_line_mrz_candidate"],
                duration_ms=self._elapsed_ms(started),
                checksum_pass_rate=0.0,
                debug={"candidate_lines": lines},
            )

        raw_line1, raw_line2 = lines[0], lines[1]
        corrected_line2, repairs = self._checksum_repair.repair_line2(raw_line2)
        issuing_country = repairs["nationality"].value
        names = self._name_normalizer.normalize_line1(raw_line1, issuing_country)
        corrected_mrz = f"{names.line1}\n{corrected_line2}"

        provenance = self._build_provenance(raw_line1, raw_line2, names, corrected_line2, repairs)
        warnings = self._warnings(repairs, names)
        checksum_pass_rate = self._checksum_pass_rate(repairs)
        return ICAOCorrectionResult(
            raw_text=raw_text,
            corrected_mrz=corrected_mrz,
            line1=names.line1,
            line2=corrected_line2,
            provenance=provenance,
            warnings=warnings,
            duration_ms=self._elapsed_ms(started),
            checksum_pass_rate=checksum_pass_rate,
            debug={"candidate_lines": lines},
        )

    def _extract_candidate_lines(self, raw_text: str) -> list[str]:
        lines = [self._normalizer.sanitize_mrz_text(line) for line in raw_text.splitlines()]
        lines = [line for line in lines if len(line) >= 12]
        if len(lines) >= 2:
            line1_index = next((index for index, line in enumerate(lines) if line.startswith("P")), 0)
            line2_index = min(len(lines) - 1, line1_index + 1)
            return [lines[line1_index], lines[line2_index]]

        compact = self._normalizer.sanitize_mrz_text(raw_text)
        start = compact.find("P")
        if start < 0:
            return []
        compact = compact[start:]
        return [compact[:44], compact[44:88]] if len(compact) >= 60 else [compact]

    def _build_provenance(self, raw_line1, raw_line2, names, corrected_line2, repairs) -> dict[str, FieldProvenance]:  # type: ignore[no-untyped-def]
        provenance = {
            "surname": self._field_validator.name(
                field_name="surname",
                original=raw_line1,
                corrected=names.surname,
                reason=names.reason,
                confidence=names.confidence,
            ),
            "given_names": self._field_validator.name(
                field_name="given_names",
                original=raw_line1,
                corrected=names.given_names,
                reason=names.reason,
                confidence=names.confidence,
            ),
            "passport_number": self._field_validator.from_repair(
                repairs["passport_number"], value=repairs["passport_number"].value.replace("<", "")
            ),
            "nationality": self._field_validator.from_repair(repairs["nationality"]),
            "issuing_country": self._field_validator.from_repair(repairs["nationality"]),
            "date_of_birth": self._field_validator.from_repair(
                repairs["date_of_birth"],
                value=self._field_validator.format_date(repairs["date_of_birth"].value, is_expiry=False),
            ),
            "sex": self._field_validator.from_repair(repairs["sex"]),
            "date_of_expiry": self._field_validator.from_repair(
                repairs["date_of_expiry"],
                value=self._field_validator.format_date(repairs["date_of_expiry"].value, is_expiry=True),
            ),
            "personal_number": self._field_validator.from_repair(
                repairs["personal_number"], value=repairs["personal_number"].value.rstrip("<")
            ),
            "mrz_line_1": FieldProvenance(raw_line1, names.line1, names.reason, "not_applicable", names.confidence),
            "mrz_line_2": FieldProvenance(
                raw_line2,
                corrected_line2,
                "line2_checksum_repair",
                repairs["composite"].checksum_status,
                repairs["composite"].confidence,
            ),
        }
        return provenance

    @staticmethod
    def _warnings(repairs, names) -> list[str]:  # type: ignore[no-untyped-def]
        warnings: list[str] = []
        for field_name, repair in repairs.items():
            if repair.checksum_status in {"fail", "review_required"}:
                warnings.append(f"review_required:{field_name}:{repair.reason}")
        if not names.surname or not names.given_names:
            warnings.append("review_required:names:incomplete_name_payload")
        return warnings

    @staticmethod
    def _checksum_pass_rate(repairs) -> float:  # type: ignore[no-untyped-def]
        checked = [
            repair for repair in repairs.values()
            if repair.checksum_status in {"pass", "fail", "review_required"}
        ]
        if not checked:
            return 0.0
        passed = sum(1 for repair in checked if repair.checksum_status == "pass")
        return round(passed / len(checked), 3)

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000, 2)
