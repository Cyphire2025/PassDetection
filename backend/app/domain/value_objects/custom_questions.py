"""Validation helpers for configurable public upload questions."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from typing import TypedDict, cast

from app.domain.exceptions.exceptions import ValidationError

MAX_CUSTOM_QUESTIONS = 20
MAX_CUSTOM_OPTIONS = 50
MAX_CUSTOM_DETAILS = 20
MAX_CUSTOM_DETAIL_VALUE_LENGTH = 500


class CustomQuestionDefinition(TypedDict):
    id: str
    label: str
    options: list[str]
    enabled: bool


class CustomDetailDefinition(TypedDict):
    id: str
    label: str
    enabled: bool


class CustomAnswerSnapshot(TypedDict):
    question_id: str
    label: str
    value: str


class CustomDetailAnswerSnapshot(TypedDict):
    detail_id: str
    label: str
    value: str


def normalize_custom_questions(
    values: Iterable[Mapping[str, object]] | None,
) -> list[CustomQuestionDefinition]:
    """Return a stable, validated JSON representation for group configuration."""

    normalized: list[CustomQuestionDefinition] = []
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    for raw in values or []:
        if len(normalized) >= MAX_CUSTOM_QUESTIONS:
            raise ValidationError(
                f"Add at most {MAX_CUSTOM_QUESTIONS} custom questions.",
                field="custom_questions",
            )
        try:
            question_id = str(uuid.UUID(str(raw.get("id", ""))))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError(
                "Every custom question requires a valid id.",
                field="custom_questions",
            ) from exc
        label = " ".join(str(raw.get("label", "")).strip().split())
        if not label or len(label) > 100:
            raise ValidationError(
                "Custom question names must be between 1 and 100 characters.",
                field="custom_questions",
            )
        label_key = label.casefold()
        if question_id in seen_ids or label_key in seen_labels:
            raise ValidationError(
                "Custom question names must be unique.",
                field="custom_questions",
            )
        seen_ids.add(question_id)
        seen_labels.add(label_key)

        options: list[str] = []
        seen_options: set[str] = set()
        # HTTP schemas validate this as a list. The cast keeps the historical
        # direct-domain behavior unchanged for callers that bypass that schema.
        for raw_option in cast(Iterable[object], raw.get("options") or []):
            option = " ".join(str(raw_option).strip().split())
            if not option:
                continue
            if len(option) > 120:
                raise ValidationError(
                    "Custom question options must be 120 characters or fewer.",
                    field="custom_questions",
                )
            option_key = option.casefold()
            if option_key in seen_options:
                continue
            seen_options.add(option_key)
            options.append(option)
        if len(options) < 2 or len(options) > MAX_CUSTOM_OPTIONS:
            raise ValidationError(
                f"Each custom question requires 2 to {MAX_CUSTOM_OPTIONS} unique options.",
                field="custom_questions",
            )
        normalized.append(
            {
                "id": question_id,
                "label": label,
                "options": options,
                "enabled": bool(raw.get("enabled", True)),
            }
        )
    return normalized


def normalize_custom_answers(
    questions: Iterable[Mapping[str, object]] | None,
    answers: Iterable[Mapping[str, object]] | None,
) -> list[CustomAnswerSnapshot]:
    """Validate answers and snapshot labels so later group edits cannot rewrite history."""

    enabled = {
        str(question["id"]): question
        for question in normalize_custom_questions(questions)
        if question["enabled"]
    }
    submitted: dict[str, str] = {}
    for raw in answers or []:
        question_id = str(raw.get("question_id", "")).strip()
        value = " ".join(str(raw.get("value", "")).strip().split())
        if question_id in submitted:
            raise ValidationError(
                "Submit one answer for each custom question.",
                field="custom_answers",
            )
        submitted[question_id] = value

    if set(submitted) - set(enabled):
        raise ValidationError(
            "One or more custom answers no longer match this upload link.",
            field="custom_answers",
        )

    snapshots: list[CustomAnswerSnapshot] = []
    for question_id, question in enabled.items():
        option_by_key = {
            str(option).casefold(): str(option) for option in question["options"]
        }
        selected = option_by_key.get(submitted.get(question_id, "").casefold())
        if not selected:
            raise ValidationError(
                f"Select an option for {question['label']}.",
                field="custom_answers",
            )
        snapshots.append(
            {
                "question_id": question_id,
                "label": question["label"],
                "value": selected,
            }
        )
    return snapshots


def normalize_custom_details(
    values: Iterable[Mapping[str, object]] | None,
) -> list[CustomDetailDefinition]:
    """Return validated free-text detail definitions with stable identifiers."""

    normalized: list[CustomDetailDefinition] = []
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    for raw in values or []:
        if len(normalized) >= MAX_CUSTOM_DETAILS:
            raise ValidationError(
                f"Add at most {MAX_CUSTOM_DETAILS} custom details.",
                field="custom_details",
            )
        try:
            detail_id = str(uuid.UUID(str(raw.get("id", ""))))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError(
                "Every custom detail requires a valid id.",
                field="custom_details",
            ) from exc
        label = " ".join(str(raw.get("label", "")).strip().split())
        if not label or len(label) > 100:
            raise ValidationError(
                "Custom detail names must be between 1 and 100 characters.",
                field="custom_details",
            )
        label_key = label.casefold()
        if detail_id in seen_ids or label_key in seen_labels:
            raise ValidationError(
                "Custom detail names must be unique.",
                field="custom_details",
            )
        seen_ids.add(detail_id)
        seen_labels.add(label_key)
        normalized.append(
            {
                "id": detail_id,
                "label": label,
                "enabled": bool(raw.get("enabled", True)),
            }
        )
    return normalized


def normalize_custom_detail_answers(
    details: Iterable[Mapping[str, object]] | None,
    answers: Iterable[Mapping[str, object]] | None,
) -> list[CustomDetailAnswerSnapshot]:
    """Validate required free-text answers and snapshot their current labels."""

    enabled = {
        str(detail["id"]): detail
        for detail in normalize_custom_details(details)
        if detail["enabled"]
    }
    submitted: dict[str, str] = {}
    for raw in answers or []:
        detail_id = str(raw.get("detail_id", "")).strip()
        value = " ".join(str(raw.get("value", "")).strip().split())
        if detail_id in submitted:
            raise ValidationError(
                "Submit one answer for each custom detail.",
                field="custom_detail_answers",
            )
        if len(value) > MAX_CUSTOM_DETAIL_VALUE_LENGTH:
            raise ValidationError(
                (
                    "Custom detail answers must be "
                    f"{MAX_CUSTOM_DETAIL_VALUE_LENGTH} characters or fewer."
                ),
                field="custom_detail_answers",
            )
        submitted[detail_id] = value

    if set(submitted) - set(enabled):
        raise ValidationError(
            "One or more custom detail answers no longer match this upload link.",
            field="custom_detail_answers",
        )

    snapshots: list[CustomDetailAnswerSnapshot] = []
    for detail_id, detail in enabled.items():
        value = submitted.get(detail_id, "")
        if not value:
            raise ValidationError(
                f"Enter {detail['label']}.",
                field="custom_detail_answers",
            )
        snapshots.append(
            {
                "detail_id": detail_id,
                "label": detail["label"],
                "value": value,
            }
        )
    return snapshots
