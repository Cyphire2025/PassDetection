"""Shared website/MCP history projection, independent of storage and transport."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.value_objects.passport_export_history import (
    PassportExportKind,
    PassportExportMode,
    PassportExportPersonSnapshot,
    validated_export_kind,
    validated_export_mode,
)


class ExportHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    export_kind: PassportExportKind
    export_mode: PassportExportMode
    baseline_export_id: uuid.UUID | None
    total_available_count: int = Field(ge=0)
    exported_count: int = Field(ge=0)
    pending_recipient_count: int = Field(ge=0)
    new_submission_count: int = Field(ge=0)
    compatible: bool
    actor_email: str | None
    created_at: datetime
    completed_at: datetime


class ExportHistoryPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: uuid.UUID
    record_available: bool
    client_name: str | None = None
    client_phone: str | None = None
    client_email: str | None = None
    passport_number: str | None = None


def project_history_item(history: Any, *, compatible: bool, new_submission_count: int) -> ExportHistoryItem:
    return ExportHistoryItem(
        id=history.id, export_kind=validated_export_kind(history.export_kind),
        export_mode=validated_export_mode(history.export_mode), baseline_export_id=history.baseline_export_id,
        total_available_count=history.total_available_count, exported_count=history.exported_count,
        pending_recipient_count=history.pending_recipient_count, compatible=compatible,
        new_submission_count=new_submission_count, actor_email=getattr(history, "actor_email", None),
        created_at=history.created_at, completed_at=history.completed_at,
    )


def project_history_people(
    people: list[PassportExportPersonSnapshot], available_ids: set[uuid.UUID],
    *, include_personal_details: bool = True,
) -> list[ExportHistoryPerson]:
    result = []
    for person in people:
        identifier = uuid.UUID(str(person["submission_id"]))
        values = {key: value for key, value in person.items() if key != "submission_id"} if include_personal_details else {}
        result.append(ExportHistoryPerson(submission_id=identifier,
            record_available=identifier in available_ids, **values))
    return result
