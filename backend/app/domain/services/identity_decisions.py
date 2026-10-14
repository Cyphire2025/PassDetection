"""Operational association rules; a match never authorizes document disclosure."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.services.traveller_names import compatible_name_words

if TYPE_CHECKING:
    from app.domain.services.traveller_identity import IdentityEvidence

SIGNAL_TYPES = frozenset({"name", "passport", "birth_date", "phone", "email", "code"})


@dataclass(frozen=True, slots=True)
class IdentityDecision:
    matched: bool
    matching_types: tuple[str, ...]
    reason: str


def compare_identity(source: "IdentityEvidence", saved: "IdentityEvidence") -> IdentityDecision:
    """O(L) bounded signals; partial names require passport plus two other types."""
    if source.conflicts or saved.conflicts:
        return IdentityDecision(False, (), "conflicting_source_fields")
    names, other_names = source.get("name"), saved.get("name")
    if len(names) != 1 or len(other_names) != 1:
        return IdentityDecision(False, (), "exact_name_required")
    exact_name = names == other_names
    if not exact_name and not compatible_name_words(next(iter(names)), next(iter(other_names))):
        return IdentityDecision(False, (), "exact_name_required")
    matches = tuple(sorted(kind for kind in SIGNAL_TYPES if source.get(kind) & saved.get(kind)))
    for kind in ("passport", "birth_date"):
        if source.get(kind) and saved.get(kind) and not source.get(kind) & saved.get(kind):
            return IdentityDecision(False, matches, f"{kind}_conflict")
    if source.get("birth_date") and not source.get("birth_date") & saved.get("birth_date"):
        return IdentityDecision(False, matches, "birth_date_required")
    if not exact_name:
        if ("passport" not in matches or len(source.get("passport")) != 1 or len(saved.get("passport")) != 1
                or len(set(matches) & {"birth_date", "phone", "email", "code"}) < 2):
            return IdentityDecision(False, matches, "partial_name_corroboration_required")
        return IdentityDecision(True, tuple(sorted((*matches, "name"))), "corroborated_partial_name_match")
    if len(matches) < 3:
        return IdentityDecision(False, matches, "three_independent_types_required")
    return IdentityDecision(True, matches, "exact_three_type_match")
