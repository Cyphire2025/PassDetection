from __future__ import annotations

import uuid

import pytest

from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.custom_questions import (
    normalize_custom_answers,
    normalize_custom_questions,
)


def _question(*, enabled: bool = True) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "label": "T-shirt size",
        "options": ["Small", "Medium", "Large"],
        "enabled": enabled,
    }


def test_custom_answers_are_validated_and_snapshot_the_question_label() -> None:
    question = _question()

    result = normalize_custom_answers(
        [question],
        [{"question_id": question["id"], "value": " medium "}],
    )

    assert result == [
        {
            "question_id": question["id"],
            "label": "T-shirt size",
            "value": "Medium",
        }
    ]


def test_disabled_custom_question_does_not_require_an_answer() -> None:
    assert normalize_custom_answers([_question(enabled=False)], []) == []


def test_custom_question_rejects_duplicate_options() -> None:
    question = _question()
    question["options"] = ["Yes", " yes "]

    with pytest.raises(ValidationError, match="2 to 50"):
        normalize_custom_questions([question])


def test_custom_answers_reject_unknown_question_ids() -> None:
    question = _question()

    with pytest.raises(ValidationError, match="no longer match"):
        normalize_custom_answers(
            [question],
            [{"question_id": str(uuid.uuid4()), "value": "Small"}],
        )
