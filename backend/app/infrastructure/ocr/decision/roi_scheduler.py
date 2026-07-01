"""ROI OCR field scheduling decisions."""

from __future__ import annotations

from dataclasses import dataclass

from app.infrastructure.ocr.voting.field_voter import FieldCandidate


@dataclass(frozen=True)
class ROISchedule:
    target_fields: set[str]
    skipped_fields: set[str]
    existing_fields: set[str]
    skip_reason: str | None = None

    @property
    def should_run(self) -> bool:
        return bool(self.target_fields)


class ROIScheduler:
    """Selects the smallest ROI OCR field set needed by current evidence."""

    _EXTRACTABLE_FIELDS = {
        "surname",
        "given_names",
        "passport_number",
        "date_of_birth",
        "sex",
        "date_of_expiry",
    }

    def schedule(self, candidates: list[FieldCandidate], fields: dict[str, str]) -> ROISchedule:
        target_fields = self.fields_to_extract(candidates, fields)
        existing_fields = {field for field in self._EXTRACTABLE_FIELDS if fields.get(field)}
        skipped_fields = self._EXTRACTABLE_FIELDS - target_fields
        skip_reason = None
        if not target_fields:
            skip_reason = "all_roi_fields_already_present_from_mrz_or_full_page_ocr"
        return ROISchedule(
            target_fields=target_fields,
            skipped_fields=skipped_fields,
            existing_fields=existing_fields,
            skip_reason=skip_reason,
        )

    def fields_to_extract(self, candidates: list[FieldCandidate], fields: dict[str, str]) -> set[str]:
        target_fields: set[str] = set()
        for field in self._EXTRACTABLE_FIELDS:
            if not fields.get(field):
                target_fields.add(field)
                continue
            if field in {"surname", "given_names"}:
                if not self._has_source_field(candidates, field, {"exact_mrz", "visual_text"}):
                    target_fields.add(field)
                continue
            if not self._has_source_field(candidates, field, {"exact_mrz", "relaxed_mrz", "visual_text", "field_roi"}):
                target_fields.add(field)
        return target_fields

    def extractable_fields(self) -> set[str]:
        return set(self._EXTRACTABLE_FIELDS)

    @staticmethod
    def _has_source_field(candidates: list[FieldCandidate], field: str, sources: set[str]) -> bool:
        return any(source in sources and bool(fields.get(field)) for fields, _weight, source in candidates)
