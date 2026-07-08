"""Corrected TD3 field validation and formatting."""

from __future__ import annotations

from dataclasses import dataclass

from app.infrastructure.ocr.correction.checksum_repair_engine import FieldRepair


@dataclass(frozen=True)
class FieldProvenance:
    original_ocr_value: str
    corrected_value: str
    correction_reason: str
    checksum_status: str
    confidence: float

    def to_dict(self) -> dict[str, str | float]:
        return {
            "original_ocr_value": self.original_ocr_value,
            "corrected_value": self.corrected_value,
            "correction_reason": self.correction_reason,
            "checksum_status": self.checksum_status,
            "confidence": self.confidence,
        }


class FieldValidator:
    """Builds output field provenance from deterministic correction results."""

    def from_repair(self, repair: FieldRepair, *, value: str | None = None) -> FieldProvenance:
        corrected = value if value is not None else repair.value
        return FieldProvenance(
            original_ocr_value=repair.original,
            corrected_value=corrected,
            correction_reason=repair.reason,
            checksum_status=repair.checksum_status,
            confidence=repair.confidence,
        )

    def name(
        self,
        *,
        field_name: str,
        original: str,
        corrected: str,
        reason: str,
        confidence: float,
    ) -> FieldProvenance:
        return FieldProvenance(
            original_ocr_value=original,
            corrected_value=corrected,
            correction_reason=f"{reason}:{field_name}",
            checksum_status="not_applicable",
            confidence=confidence,
        )

    @staticmethod
    def format_date(value: str, *, is_expiry: bool) -> str:
        if len(value) != 6 or not value.isdigit():
            return ""
        yy = int(value[:2])
        year = 2000 + yy if is_expiry else (1900 + yy if yy > 30 else 2000 + yy)
        return f"{year:04d}-{value[2:4]}-{value[4:6]}"
