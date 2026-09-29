"""Save only changed, reviewed contact/detail values; never raw passport snapshots."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.passports.client_details_fields import DIRECT_FIELDS, scalar_value
from app.application.use_cases.whatsapp.group_submission_matching import (
    normalize_matching_field_key,
)
from app.application.use_cases.whatsapp.imported_broadcast_phone import (
    imported_phone_column_priority,
)
from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.mcp_record_revision_models import MCPRecordRevisionModel

_FIELDS = frozenset(
    {
        "client_email",
        "client_phone",
        "departure_city",
        "nearest_domestic_airport",
        "base_city",
        "staff_code",
        "agent_employee_type",
        "agent_employee_code",
        "designation",
        "agency_dealership_name",
        "meal_preference",
    }
)


def _snapshot(submission: PassportSubmission, changed: tuple[str, ...]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in changed:
        if ":" in key:
            kind, item_id = key.split(":", 1)
            collection = {
                "question_id": "custom_answers",
                "detail_id": "custom_detail_answers",
            }.get(kind)
            if collection is None:
                raise ValueError("Unsupported revision field")
            uuid.UUID(item_id)
            item = next(
                (item for item in getattr(submission, collection) if str(item[kind]) == item_id),
                None,
            )
            values[key] = (
                {kind: item[kind], "label": item.get("label"), "value": item.get("value")}
                if item
                else None
            )
            continue
        if key not in _FIELDS:
            raise ValueError("Unsupported revision field")
        canonical = {"client_phone": "phone_number", "client_email": "email"}.get(
            key
        ) or normalize_matching_field_key(key)
        canonical_keys = {canonical}
        if key == "departure_city":
            canonical_keys.add("nearest_international_airport")
        value: dict[str, Any] = {"value": scalar_value(submission, key)}
        if key in DIRECT_FIELDS:
            value["direct"] = getattr(submission, key)
        for name in ("confirmed_fields", "staff_metadata"):
            source = getattr(submission, name) or {}
            value[name] = {
                raw: entry
                for raw, entry in source.items()
                if normalize_matching_field_key(raw) in canonical_keys
                or (key == "client_phone" and imported_phone_column_priority(raw) is not None)
            }
        values[key] = value
    return copy.deepcopy(values)


async def preserve_client_detail_revision(
    session: AsyncSession,
    *,
    operation_id: uuid.UUID,
    before: PassportSubmission,
    after: PassportSubmission,
    changed_fields: tuple[str, ...],
) -> uuid.UUID:
    """Same transaction as correction. No generic audit/log includes these PII values."""
    if not changed_fields or (before.id, before.agency_id, before.group_id) != (
        after.id,
        after.agency_id,
        after.group_id,
    ):
        raise ValueError("Revision requires one unchanged source identity and changed details")
    revision = MCPRecordRevisionModel(
        id=uuid.uuid4(),
        operation_id=operation_id,
        entity_type="passport_submission",
        entity_id=before.id,
        agency_id=before.agency_id,
        group_id=before.group_id,
        before_values=_snapshot(before, changed_fields),
        after_values=_snapshot(after, changed_fields),
    )
    session.add(revision)
    await session.flush()
    return revision.id
