"""Apply narrow staff corrections without altering passport verification or documents."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from app.application.use_cases.passports.client_details_fields import (
    DIRECT_FIELDS,
    client_detail_fields,
    client_details_payload,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    normalize_matching_field_key,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.custom_questions import (
    CustomAnswerSnapshot,
    CustomDetailAnswerSnapshot,
)


def _validate_value(value: object, field: Mapping[str, Any]) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValidationError("Client details must contain text.")
    cleaned = " ".join((value or "").split())
    if not cleaned:
        if field["required"]:
            raise ValidationError(f"Enter {field['label']}.")
        return None
    if len(cleaned) > field["max_length"]:
        raise ValidationError(f"{field['label']} is too long.")
    if options := field.get("options"):
        matched = next(
            (option for option in options if option.casefold() == cleaned.casefold()), None
        )
        if matched is None:
            raise ValidationError(f"Select an available option for {field['label']}.")
        return str(matched)
    return cleaned


def _patch_answers(
    saved: Sequence[Mapping[str, object]],
    changes: Sequence[Mapping[str, object]],
    descriptors: Sequence[Mapping[str, Any]],
    *,
    id_key: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    allowed = {str(item[id_key]): item for item in descriptors}
    result = [dict(item) for item in saved]
    positions = {str(item[id_key]): i for i, item in enumerate(result)}
    seen: set[str] = set()
    changed = []
    for change in changes:
        item_id = str(change.get(id_key, ""))
        if item_id in seen or item_id not in allowed or set(change) != {id_key, "value"}:
            raise ValidationError("Choose each existing custom detail only once.")
        seen.add(item_id)
        descriptor = allowed[item_id]
        value = _validate_value(change["value"], descriptor)
        if value == (descriptor.get("value") or None):
            continue
        # Keep a blank snapshot so its historical label and editable identity survive clearing.
        snapshot = {id_key: item_id, "label": descriptor["label"], "value": value or ""}
        if item_id in positions:
            result[positions[item_id]] = snapshot
        else:
            result.append(snapshot)
        changed.append(f"{id_key}:{item_id}")
    return result, changed


def correct_client_details(
    submission: PassportSubmission,
    group: ClientGroup,
    changes: Mapping[str, Any],
) -> tuple[PassportSubmission, tuple[str, ...]]:
    """Validate all edits before touching the entity; sparse patches preserve omitted fields."""
    scalar_fields = {field.key: field for field in client_detail_fields(submission, group)}
    unknown = set(changes) - set(scalar_fields) - {"custom_answers", "custom_detail_answers"}
    if unknown:
        raise ValidationError("One or more details are not available for this submission.")
    updated = replace(submission)
    changed: list[str] = []
    confirmed = dict(submission.confirmed_fields or {})
    metadata = dict(submission.staff_metadata or {})
    for key, value in changes.items():
        if key not in scalar_fields:
            continue
        descriptor = scalar_fields[key]
        cleaned = _validate_value(value, descriptor.__dict__)
        if key == "client_phone" and cleaned:
            if re.search(r"[^\d\s()+.\-]", cleaned):
                raise ValidationError("Enter a valid phone number.", field=key)
            digits = re.sub(r"\D", "", cleaned)
            if not 7 <= len(digits) <= 15:
                raise ValidationError("Enter a valid phone number.", field=key)
            cleaned = ("+" if cleaned.startswith("+") else "") + digits
        if key == "client_email" and cleaned:
            cleaned = cleaned.lower()
        if cleaned == (descriptor.value or None):
            continue
        if key in DIRECT_FIELDS:
            setattr(updated, key, cleaned)
        if key in scalar_fields:
            # Store corrections in the same authoritative layer used by the existing UI.
            # Correct aliases too, so a former value cannot remain matchable through an
            # imported metadata key. Original OCR is retained, not rewritten.
            canonical = {"client_phone": "phone_number", "client_email": "email"}.get(
                key
            ) or normalize_matching_field_key(key)
            canonical_keys = {canonical}
            if key == "departure_city":
                canonical_keys.add("nearest_international_airport")
            aliases = {key} if key not in DIRECT_FIELDS else set()
            for source in (confirmed, metadata, submission.extracted_fields or {}):
                aliases.update(
                    raw for raw in source if normalize_matching_field_key(raw) in canonical_keys
                )
            for alias in aliases:
                confirmed[alias] = cleaned or ""
                if alias in metadata:
                    metadata[alias] = cleaned or ""
        changed.append(key)
    payload = client_details_payload(submission, group)
    for collection, id_key in (
        ("custom_answers", "question_id"),
        ("custom_detail_answers", "detail_id"),
    ):
        if collection not in changes:
            continue
        answers, answer_changes = _patch_answers(
            getattr(submission, collection),
            changes[collection],
            payload[collection],
            id_key=id_key,
        )
        if answer_changes:
            if collection == "custom_answers":
                updated.custom_answers = cast(list[CustomAnswerSnapshot], answers)
            else:
                updated.custom_detail_answers = cast(list[CustomDetailAnswerSnapshot], answers)
            changed.extend(answer_changes)
    if changed:
        if confirmed and not submission.confirmed_fields:
            # Legacy office records can have only extracted fields. The detail UI
            # chooses confirmed_fields OR extracted_fields, so the first auxiliary
            # correction must retain every existing scalar field in that view.
            effective = {
                key: str(value) if value is not None else ""
                for key, value in (submission.extracted_fields or {}).items()
                if value is None or isinstance(value, (str, int, float, bool))
            }
            confirmed = {**effective, **confirmed}
        updated.confirmed_fields = confirmed or None
        updated.staff_metadata = metadata or None
        updated.updated_at = datetime.now(tz=UTC)
    return updated, tuple(changed)
