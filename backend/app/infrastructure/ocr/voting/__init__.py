"""Field candidate aggregation."""

from app.infrastructure.ocr.voting.evidence_merger import (
    EvidenceFusionResult,
    EvidenceMerger,
    FieldDecision,
    FieldEvidence,
)
from app.infrastructure.ocr.voting.field_voter import FieldCandidate, FieldVoter

__all__ = [
    "EvidenceFusionResult",
    "EvidenceMerger",
    "FieldCandidate",
    "FieldDecision",
    "FieldEvidence",
    "FieldVoter",
]
