"""Legacy-compatible weighted field candidate voting."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TypeAlias

from app.infrastructure.ocr.voting.evidence_merger import (
    EvidenceFusionResult,
    EvidenceMerger,
    FieldEvidence,
)

FieldCandidate: TypeAlias = tuple[dict[str, str], int, str]


class FieldVoter:
    """Aggregates field candidates while keeping normalization policy injectable."""

    _EXACT_FIELDS = (
        "surname",
        "given_names",
        "passport_number",
        "nationality",
        "issuing_country",
        "date_of_birth",
        "date_of_expiry",
        "sex",
    )

    def __init__(
        self,
        *,
        clean_fields: Callable[[dict[str, str]], dict[str, str]],
        is_plausible: Callable[[str, str], bool],
        value_quality: Callable[[str, str], int],
        is_name_plausible: Callable[[str], bool],
    ) -> None:
        self._clean_fields = clean_fields
        self._is_plausible = is_plausible
        self._value_quality = value_quality
        self._is_name_plausible = is_name_plausible
        self._evidence_merger = EvidenceMerger(
            is_plausible=is_plausible,
            value_quality=value_quality,
        )

    def vote(self, candidates: list[FieldCandidate]) -> dict[str, str]:
        return self.fuse(candidates).fields

    def fuse(self, candidates: list[FieldCandidate]) -> EvidenceFusionResult:
        evidence: list[FieldEvidence] = []
        for fields, weight, source in candidates:
            for key, value in self._clean_fields(fields).items():
                evidence.append(
                    FieldEvidence(
                        field=key,
                        value=value,
                        source=source,
                        confidence=min(1.0, max(0.05, weight / 10)),
                        preprocessing_variant=self._variant_for(source),
                        ocr_engine=self._engine_for(source),
                        validation_status="validated" if source == "exact_mrz" else "unvalidated",
                        metadata={"legacy_weight": weight},
                    )
                )
        return self._evidence_merger.merge(evidence)

    def _legacy_vote(self, candidates: list[FieldCandidate]) -> dict[str, str]:
        """Retained as a behavioral reference during evidence calibration."""
        selected: dict[str, str] = {}
        for fields, _, source in candidates:
            if source == "exact_mrz":
                cleaned = self._clean_fields(fields)
                selected.update(
                    {key: cleaned[key] for key in self._EXACT_FIELDS if cleaned.get(key)}
                )

        scores: dict[str, dict[str, int]] = {}
        sources: dict[str, dict[str, set[str]]] = {}
        for fields, weight, source in candidates:
            for key, value in self._clean_fields(fields).items():
                scores.setdefault(key, {})
                sources.setdefault(key, {})
                scores[key][value] = (
                    scores[key].get(value, 0) + weight + self._source_boost(source, key, value)
                )
                sources[key].setdefault(value, set()).add(source)

        for key, values in scores.items():
            if key in selected:
                continue
            ranked = sorted(
                values.items(),
                key=lambda item: (
                    item[1] + min(3, len(sources[key].get(item[0], set()))),
                    self._value_quality(key, item[0]),
                    len(item[0]),
                ),
                reverse=True,
            )
            if ranked and self._is_plausible(key, ranked[0][0]):
                selected[key] = ranked[0][0]
        return selected

    @staticmethod
    def _variant_for(source: str) -> str:
        return {
            "field_roi": "field_roi",
            "visual_text": "full_document",
            "exact_mrz": "mrz_exact",
            "relaxed_mrz": "mrz_relaxed",
        }.get(source, "unknown")

    @staticmethod
    def _engine_for(source: str) -> str:
        return {
            "field_roi": "tesseract",
            "visual_text": "ocr_ensemble",
            "exact_mrz": "passporteye_or_parser",
            "relaxed_mrz": "passporteye_or_parser",
        }.get(source, "unknown")

    def _source_boost(self, source: str, key: str, value: str) -> int:
        if (
            source == "field_roi"
            and key == "passport_number"
            and re.fullmatch(r"[A-Z][0-9]{7}", value)
        ):
            return 12
        if (
            source == "visual_text"
            and key == "passport_number"
            and re.fullmatch(r"[A-Z][0-9]{7}", value)
        ):
            return 4
        if (
            source == "visual_text"
            and key in {"surname", "given_names"}
            and self._is_name_plausible(value)
        ):
            return 3
        if source == "exact_mrz":
            return 5
        if source == "relaxed_mrz" and key in {"surname", "given_names", "passport_number"}:
            return -6
        if source == "visual_text" and key == "passport_number":
            return -2
        return 0
