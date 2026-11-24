"""Pure client submission replay rules; the submission use case owns effects."""

from __future__ import annotations

import uuid

from app.domain.entities.entities import PassportSubmission
from app.domain.value_objects.custom_questions import (
    CustomAnswerSnapshot,
    CustomDetailAnswerSnapshot,
)
from app.domain.value_objects.phone_number import phone_numbers_equal


def _is_exact_replay(
    submission: PassportSubmission,
    *,
    clean_fields: dict[str, str],
    client_email: str | None,
    client_phone: str | None,
    departure_city: str | None,
    nearest_domestic_airport: str | None,
    submission_mode: str,
    family_group_id: uuid.UUID | None,
    family_member_index: int | None,
    family_relation: str | None,
    family_gender: str | None,
    family_head_name: str | None,
    family_head_email: str | None,
    family_head_phone: str | None,
    family_broadcast_to_member: bool,
    custom_answers: list[CustomAnswerSnapshot],
    custom_detail_answers: list[CustomDetailAnswerSnapshot],
) -> bool:
    return (
        dict(submission.confirmed_fields or {}) == clean_fields
        and submission.client_email == client_email
        and phone_numbers_equal(submission.client_phone, client_phone)
        and submission.departure_city == departure_city
        and submission.nearest_domestic_airport == nearest_domestic_airport
        and submission.submission_mode == submission_mode
        and submission.family_group_id == family_group_id
        and submission.family_member_index == family_member_index
        and submission.family_relation == family_relation
        and submission.family_gender == family_gender
        and submission.family_head_name == family_head_name
        and submission.family_head_email == family_head_email
        and phone_numbers_equal(submission.family_head_phone, family_head_phone)
        and submission.family_broadcast_to_member == family_broadcast_to_member
        and list(submission.custom_answers or []) == custom_answers
        and list(submission.custom_detail_answers or []) == custom_detail_answers
    )
