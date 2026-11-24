"""Normalize saved and newly entered answers for one reviewed trip."""

from __future__ import annotations

from typing import NamedTuple, cast

from app.application.platform_policies import PlatformPolicies
from app.application.travellers.current_details import normalize_current_details
from app.application.travellers.history import ReviewContext
from app.application.travellers.requirements import TripAnswers
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.custom_questions import (
    CustomAnswerSnapshot,
    CustomDetailAnswerSnapshot,
    normalize_custom_answers,
    normalize_custom_detail_answers,
)


class ReuseAnswers(NamedTuple):
    details: dict[str, str]
    phone: object
    questions: list[CustomAnswerSnapshot]
    custom_details: list[CustomDetailAnswerSnapshot]


def normalize_reuse_answers(
    context: ReviewContext,
    policies: PlatformPolicies,
    review: dict[str, object],
    *,
    custom_answers: dict[str, str],
    custom_detail_answers: dict[str, str],
    current_details: dict[str, str],
    verified_phone_override: str | None,
) -> ReuseAnswers:
    """Keep original normalization and validation order before idempotency checks."""
    scope = context.scope
    saved = cast(TripAnswers, review["saved_answers"])
    details = normalize_current_details(
        scope.group, policies, {**saved["current_details"], **current_details}
    )
    phone = verified_phone_override or review["contact_phone"]
    if policies.require_client_phone and not phone:
        raise ValidationError(
            "Verify a current phone number before submitting.", field="client_phone"
        )
    questions = normalize_custom_answers(
        scope.group.custom_questions,
        [
            {"question_id": key, "value": value}
            for key, value in {**saved["custom_answers"], **custom_answers}.items()
        ],
    )
    custom_details = normalize_custom_detail_answers(
        scope.group.custom_details,
        [
            {"detail_id": key, "value": value}
            for key, value in {**saved["custom_detail_answers"], **custom_detail_answers}.items()
        ],
    )
    return ReuseAnswers(details, phone, questions, custom_details)
