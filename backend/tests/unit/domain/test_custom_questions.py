from __future__ import annotations

import uuid

import pytest

from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.custom_questions import (
    normalize_custom_answers,
    normalize_custom_detail_answers,
    normalize_custom_details,
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


def test_custom_detail_answers_are_required_and_snapshot_the_heading() -> None:
    detail = {
        "id": str(uuid.uuid4()),
        "label": "  Badge   name ",
        "enabled": True,
    }

    result = normalize_custom_detail_answers(
        [detail],
        [{"detail_id": detail["id"], "value": "  Nipun   Vashistha "}],
    )

    assert result == [
        {
            "detail_id": detail["id"],
            "label": "Badge name",
            "value": "Nipun Vashistha",
        }
    ]


def test_disabled_custom_detail_ignores_an_absent_answer() -> None:
    detail = {
        "id": str(uuid.uuid4()),
        "label": "Badge name",
        "enabled": False,
    }

    assert normalize_custom_detail_answers([detail], []) == []


def test_custom_details_reject_duplicate_headings_case_insensitively() -> None:
    first = {
        "id": str(uuid.uuid4()),
        "label": "Badge name",
        "enabled": True,
    }
    second = {
        "id": str(uuid.uuid4()),
        "label": " badge NAME ",
        "enabled": True,
    }

    with pytest.raises(ValidationError, match="must be unique"):
        normalize_custom_details([first, second])
