"""Structured OCR evidence fusion with explainable field decisions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class FieldEvidence:
    field: str
    value: str
    source: str
    confidence: float
    preprocessing_variant: str
    ocr_engine: str
    validation_status: str = "unvalidated"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FieldDecision:
    value: str
    confidence: float
    agreement: float
    supporting_evidence: tuple[FieldEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": self.confidence,
            "agreement": self.agreement,
            "supporting_evidence": [item.to_dict() for item in self.supporting_evidence],
        }


@dataclass(frozen=True)
class EvidenceFusionResult:
    fields: dict[str, str]
    decisions: dict[str, FieldDecision]

    @property
    def field_confidence(self) -> dict[str, float]:
        return {key: value.confidence for key, value in self.decisions.items()}

    def to_dict(self) -> dict[str, Any]:
        return {key: value.to_dict() for key, value in self.decisions.items()}


class EvidenceMerger:
    """Fuses normalized field evidence using source reliability and agreement."""

    _SOURCE_RELIABILITY = {
        "exact_mrz": 1.0,
        "field_roi": 0.82,
        "visual_text": 0.72,
        "relaxed_mrz": 0.62,
        "vision_ai": 0.68,
    }

    def __init__(
        self,
        *,
        is_plausible: Callable[[str, str], bool],
        value_quality: Callable[[str, str], int],
    ) -> None:
        self._is_plausible = is_plausible
        self._value_quality = value_quality

    def merge(self, evidence: list[FieldEvidence]) -> EvidenceFusionResult:
        grouped: dict[str, list[FieldEvidence]] = defaultdict(list)
        for item in evidence:
            if item.value and self._is_plausible(item.field, item.value):
                grouped[item.field].append(item)

        fields: dict[str, str] = {}
        decisions: dict[str, FieldDecision] = {}
        for field_name, field_evidence in grouped.items():
            decision = self._decide(field_name, field_evidence)
            if decision is not None:
                fields[field_name] = decision.value
                decisions[field_name] = decision
        return EvidenceFusionResult(fields=fields, decisions=decisions)

    def _decide(
        self,
        field_name: str,
        evidence: list[FieldEvidence],
    ) -> FieldDecision | None:
        exact = [item for item in evidence if item.source == "exact_mrz"]
        candidates = exact or evidence
        scores: dict[str, float] = defaultdict(float)
        sources: dict[str, set[str]] = defaultdict(set)
        engines: dict[str, set[str]] = defaultdict(set)
        supporting: dict[str, list[FieldEvidence]] = defaultdict(list)

        for item in candidates:
            reliability = self._SOURCE_RELIABILITY.get(item.source, 0.5)
            scores[item.value] += max(0.0, min(1.0, item.confidence)) * reliability
            sources[item.value].add(item.source)
            engines[item.value].add(item.ocr_engine)
            supporting[item.value].append(item)

        if not scores:
            return None

        ranked = sorted(
            scores,
            key=lambda value: (
                scores[value] + min(0.12, 0.04 * (len(sources[value]) - 1)),
                self._value_quality(field_name, value),
                len(value),
            ),
            reverse=True,
        )
        selected = ranked[0]
        total_score = sum(scores.values())
        agreement = scores[selected] / total_score if total_score else 0.0
        diversity_bonus = min(0.12, 0.04 * (len(sources[selected]) + len(engines[selected]) - 2))
        confidence = min(0.99, (agreement * 0.72) + (scores[selected] / max(1, len(candidates)) * 0.28) + diversity_bonus)
        return FieldDecision(
            value=selected,
            confidence=round(confidence, 3),
            agreement=round(agreement, 3),
            supporting_evidence=tuple(supporting[selected]),
        )
