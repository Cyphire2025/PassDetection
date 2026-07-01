"""Composition root for OCR decision policies."""

from __future__ import annotations

from app.infrastructure.ocr.decision.field_selection import FieldCompletenessPolicy
from app.infrastructure.ocr.decision.roi_scheduler import ROISchedule, ROIScheduler
from app.infrastructure.ocr.voting.field_voter import FieldCandidate


class OCRDecisionEngine:
    """Facade for OCR optimization decisions used by orchestration services."""

    def __init__(
        self,
        *,
        field_completeness: FieldCompletenessPolicy | None = None,
        roi_scheduler: ROIScheduler | None = None,
    ) -> None:
        self.field_completeness = field_completeness or FieldCompletenessPolicy()
        self.roi_scheduler = roi_scheduler or ROIScheduler()

    def schedule_roi(self, candidates: list[FieldCandidate], fields: dict[str, str]) -> ROISchedule:
        return self.roi_scheduler.schedule(candidates, fields)

    def should_run_passporteye(self, *, validation_status: str, fields: dict[str, str]) -> bool:
        return not (
            validation_status == "valid"
            and self.field_completeness.has_complete_core_fields(fields)
        )

    def passporteye_skip_reason(self, *, validation_status: str, fields: dict[str, str]) -> str:
        if validation_status == "valid" and self.field_completeness.has_complete_core_fields(fields):
            return "valid_complete_fields_from_mrz_strip_or_full_page_ocr"
        return "not_skipped"

    def should_try_roi_before_mrz_strip(self, schedule: ROISchedule) -> bool:
        return schedule.should_run and len(schedule.target_fields) <= 1

    def should_run_mrz_strip(self, *, validation_status: str, fields: dict[str, str]) -> bool:
        return not (
            validation_status == "valid"
            and self.field_completeness.has_complete_core_fields(fields)
        )

    def mrz_strip_skip_reason(self, *, validation_status: str, fields: dict[str, str]) -> str:
        if validation_status == "valid" and self.field_completeness.has_complete_core_fields(fields):
            return "valid_complete_fields_from_full_page_ocr_or_targeted_roi"
        return "not_skipped"
