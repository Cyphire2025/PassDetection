"""Canonical links only from the owner's visible, unambiguous candidate aliases."""

from __future__ import annotations

import uuid

from app.domain.value_objects.email_ai_analysis import EmailAnalysisResult
from app.infrastructure.email.ai_context import EmailAiContext


def _canonical_link_ids(
    *,
    context: EmailAiContext,
    result: EmailAnalysisResult,
    confidence_threshold: float,
) -> tuple[uuid.UUID | None, list[str]]:
    """Persist canonical links only when provider candidates are unambiguous."""

    group_ids: list[uuid.UUID] = []
    linked_group_aliases: list[str] = []
    passenger_ids: list[str] = []
    linked_passenger_aliases: list[str] = []
    for link in result.candidate_links:
        if link.confidence < confidence_threshold:
            continue
        entity = context.aliases.get(link.alias)
        if entity is None:
            continue
        entity_type, entity_id = entity
        if entity_type == "group" and entity_id not in group_ids:
            group_ids.append(entity_id)
            linked_group_aliases.append(link.alias)
        elif entity_type == "passenger":
            passenger_id = str(entity_id)
            if passenger_id not in passenger_ids:
                passenger_ids.append(passenger_id)
                linked_passenger_aliases.append(link.alias)

    if len(group_ids) > 1:
        return None, []

    candidates = {candidate.alias: candidate for candidate in context.request.visible_candidates}
    selected_group_alias = linked_group_aliases[0] if len(linked_group_aliases) == 1 else None
    passenger_parent_aliases: set[str] = set()
    passenger_names: list[str] = []
    for alias in linked_passenger_aliases:
        candidate = candidates.get(alias)
        if candidate is None:
            continue
        parent_alias = _candidate_fact(candidate.safe_facts, "group alias")
        if parent_alias:
            passenger_parent_aliases.add(parent_alias)
        name_fact = next(
            (
                fact.removeprefix("name:").strip().casefold()
                for fact in candidate.safe_facts
                if fact.casefold().startswith("name:")
            ),
            "",
        )
        if name_fact:
            passenger_names.append(name_fact)
    parent_mismatch = bool(
        selected_group_alias is not None
        and any(parent_alias != selected_group_alias for parent_alias in passenger_parent_aliases)
    )
    if (
        len(passenger_names) != len(set(passenger_names))
        or len(passenger_parent_aliases) > 1
        or parent_mismatch
    ):
        passenger_ids = []

    canonical_group_id = group_ids[0] if len(group_ids) == 1 else None
    if canonical_group_id is None and len(passenger_parent_aliases) == 1:
        parent_alias = next(iter(passenger_parent_aliases))
        parent_entity = context.aliases.get(parent_alias)
        if parent_entity is not None and parent_entity[0] == "group":
            canonical_group_id = parent_entity[1]
    return canonical_group_id, passenger_ids


def _authorized_context_group_name(
    context: EmailAiContext,
    linked_group_id: uuid.UUID | None,
) -> str | None:
    """Return a bounded group name only from the owner's authorized context."""

    if linked_group_id is None:
        return None
    group_alias = next(
        (
            alias
            for alias, (entity_type, entity_id) in context.aliases.items()
            if entity_type == "group" and entity_id == linked_group_id
        ),
        None,
    )
    if group_alias is None:
        return None
    candidate = next(
        (item for item in context.request.visible_candidates if item.alias == group_alias),
        None,
    )
    if candidate is None:
        return None
    for fact in candidate.safe_facts:
        label, separator, value = fact.partition(":")
        if separator and label.strip().casefold() == "name":
            normalized = " ".join(value.split())[:160]
            return normalized or None
    return None


def _candidate_links_are_ambiguous(
    *,
    context: EmailAiContext,
    result: EmailAnalysisResult,
) -> bool:
    group_aliases: set[str] = set()
    for link in result.candidate_links:
        entity = context.aliases.get(link.alias)
        if entity is not None and entity[0] == "group":
            group_aliases.add(link.alias)
    if len(group_aliases) > 1:
        return True
    candidates = {candidate.alias: candidate for candidate in context.request.visible_candidates}
    selected_group_alias = next(iter(group_aliases), None)
    passenger_parent_aliases: set[str] = set()
    passenger_names: list[str] = []
    for link in result.candidate_links:
        entity = context.aliases.get(link.alias)
        if entity is None or entity[0] != "passenger":
            continue
        candidate = candidates.get(link.alias)
        if candidate is None:
            continue
        parent_alias = _candidate_fact(candidate.safe_facts, "group alias")
        if parent_alias:
            passenger_parent_aliases.add(parent_alias)
        name_fact = next(
            (
                fact.removeprefix("name:").strip().casefold()
                for fact in candidate.safe_facts
                if fact.casefold().startswith("name:")
            ),
            "",
        )
        if name_fact:
            passenger_names.append(name_fact)
    return bool(
        len(passenger_names) != len(set(passenger_names))
        or len(passenger_parent_aliases) > 1
        or (
            selected_group_alias is not None
            and any(
                parent_alias != selected_group_alias for parent_alias in passenger_parent_aliases
            )
        )
    )


def _candidate_fact(safe_facts: list[str], label: str) -> str | None:
    prefix = f"{label}:"
    for fact in safe_facts:
        if fact.casefold().startswith(prefix.casefold()):
            value = fact[len(prefix) :].strip()
            return value or None
    return None
