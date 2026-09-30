"""Pure validation of retained passport export checkpoints; never log stored values."""

from __future__ import annotations

import uuid
from typing import Any, Literal, cast

PassportExportKind = Literal["passport_images", "passport_excel"]
PassportExportMode = Literal["all", "incremental"]
PassportExportPersonSnapshot = dict[str, str | None]
PERSON_FIELDS = ("client_name", "client_phone", "client_email", "passport_number")


def validated_export_people_snapshot(
    values: object, *, exported_submission_ids: list[uuid.UUID],
) -> list[PassportExportPersonSnapshot]:
    if not isinstance(values, list) or len(values) != len(exported_submission_ids):
        raise ValueError("Export person details do not match the payload count.")
    canonical: list[PassportExportPersonSnapshot] = []
    for expected_id, raw in zip(exported_submission_ids, values, strict=True):
        if not isinstance(raw, dict):
            raise ValueError("Export person details contain an invalid record.")
        try:
            submission_id = uuid.UUID(str(raw.get("submission_id")))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Export person details contain an invalid submission ID.") from exc
        if submission_id != expected_id:
            raise ValueError("Export person details are not aligned to the payload.")
        item: PassportExportPersonSnapshot = {"submission_id": str(submission_id)}
        for name in PERSON_FIELDS:
            value = raw.get(name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"Export person details contain an invalid {name}.")
            item[name] = value
        canonical.append(item)
    return canonical


def validated_export_history_ids(
    history: Any, *, field_name: Literal["snapshot_submission_ids", "exported_submission_ids"],
) -> set[uuid.UUID]:
    try:
        parsed = [uuid.UUID(str(value)) for value in (getattr(history, field_name) or [])]
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError("The export history entry contains an invalid ID.") from exc
    expected = history.total_available_count if field_name == "snapshot_submission_ids" else history.exported_count
    if len(parsed) != expected or len(set(parsed)) != expected:
        raise ValueError("The export history entry failed its integrity check.")
    return set(parsed)


def validated_export_kind(value: str) -> PassportExportKind:
    if value not in {"passport_images", "passport_excel"}:
        raise ValueError("The export history entry contains an invalid export kind.")
    return cast(PassportExportKind, value)


def validated_export_mode(value: str) -> PassportExportMode:
    if value not in {"all", "incremental"}:
        raise ValueError("The export history entry contains an invalid export mode.")
    return cast(PassportExportMode, value)


def validated_export_history_people(history: Any) -> list[PassportExportPersonSnapshot]:
    validated_export_history_ids(history, field_name="exported_submission_ids")
    ordered = [uuid.UUID(str(value)) for value in (history.exported_submission_ids or [])]
    return validated_export_people_snapshot(history.exported_people_snapshot, exported_submission_ids=ordered)
