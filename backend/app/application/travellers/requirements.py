"""Preserve unchanged answers from this trip only when requirements are edited.

O(q) time/space, q <=60 configured fields. Stored definition digests avoid copying
large option lists into each participation. No earlier-trip answer is consulted.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.application.platform_policies import PlatformPolicies
from app.application.travellers.current_details import detail_fields
from app.domain.value_objects.upload_configuration import configuration_for
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.traveller_reuse_models import TravellerParticipationModel

TripAnswers = dict[str, dict[str, str]]


def missing_document_requirements(group: ClientGroupModel, available_sides: set[str]) -> list[str]:
    """Current-trip uploads required after selecting retained document assets."""
    config = configuration_for(group)
    missing = [f"passport_{side}" for side in config.passport_upload_pages
        if config.passport_enabled and side not in available_sides]
    if group.require_selfie or (config.visa_photo_required and config.visa_photo_live_capture):
        missing.append("fresh_photo")
    elif config.visa_photo_required and "photo" not in available_sides:
        missing.append("visa_photo")
    if group.relation_with_qualifier_enabled:
        missing.append("qualifier_relationship")
    return missing


def requirement_signatures(group: ClientGroupModel, policies: PlatformPolicies) -> TripAnswers:
    def digest(value: object) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "custom_answers": {item["id"]: digest(item) for item in group.custom_questions if item["enabled"]},
        "custom_detail_answers": {item["id"]: digest(item) for item in group.custom_details if item["enabled"]},
        "current_details": {item["key"]: digest(item) for item in detail_fields(group, policies)},
    }


def saved_current_answers(
    participation: TravellerParticipationModel | None, group: ClientGroupModel,
    policies: PlatformPolicies,
) -> TripAnswers:
    current = requirement_signatures(group, policies)
    result: TripAnswers = {key: {} for key in current}
    if participation is None or participation.group_id != group.id or participation.status == "withdrawn":
        return result
    stored = participation.confirmations.get("requirement_signatures", {})
    if not isinstance(stored, dict):
        return result
    for section, signatures in current.items():
        previous = stored.get(section, {})
        if not isinstance(previous, dict):
            continue
        answers: Any = participation.answers.get(section, {})
        if section != "current_details":
            identifier_key = "question_id" if section == "custom_answers" else "detail_id"
            answers = {row.get(identifier_key): row.get("value") for row in answers if isinstance(row, dict)} if isinstance(answers, list) else {}
        if not isinstance(answers, dict):
            continue
        for key, signature in signatures.items():
            value = answers.get(key)
            if previous.get(key) == signature and isinstance(value, str):
                result[section][key] = value
    return result
