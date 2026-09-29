"""Shared two-phase export completion, with transaction ownership at the caller."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.domain.entities.entities import User
from app.infrastructure.database.models import PassportExportHistoryModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_export_history_repository import (
    validated_export_people_snapshot,
)


class ExportDeliveryConflict(ValueError):
    pass


def validate_export_checkpoint(history: PassportExportHistoryModel) -> None:
    """Validate the frozen payload and cumulative checkpoint without reading live people."""
    try:
        snapshot = [uuid.UUID(str(value)) for value in (history.snapshot_submission_ids or [])]
        exported = [uuid.UUID(str(value)) for value in (history.exported_submission_ids or [])]
        if (
            len(snapshot) != history.total_available_count
            or len(set(snapshot)) != len(snapshot)
            or len(exported) != history.exported_count
            or len(set(exported)) != len(exported)
            or not set(exported).issubset(snapshot)
            or history.export_kind not in {"passport_excel", "passport_images"}
            or history.export_mode not in {"all", "incremental"}
        ):
            raise ValueError()
        validated_export_people_snapshot(
            history.exported_people_snapshot, exported_submission_ids=exported
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise ExportDeliveryConflict("This prepared download failed its integrity check.") from exc


async def complete_export_delivery(
    *,
    history: PassportExportHistoryModel,
    actor: User,
    agency_id: uuid.UUID,
    audit: AuditLogRepository,
) -> bool:
    """Transition a caller-authorized, row-locked checkpoint once; never commit here.

    The transport must first establish successful browser delivery or verified
    connector delivery. Generation or a partial HTTP stream is not completion.
    """
    if history.status == "completed":
        if history.completed_at is None:
            raise ExportDeliveryConflict("This prepared download failed its integrity check.")
        return False
    if history.status != "prepared" or history.completed_at is not None:
        raise ExportDeliveryConflict("This prepared download is in an invalid state.")
    validate_export_checkpoint(history)
    history.status = "completed"
    history.completed_at = datetime.now(UTC)
    await audit.record(
        action=(
            "passport_group_images_exported"
            if history.export_kind == "passport_images"
            else "passport_group_exported"
        ),
        entity_type="client_group",
        entity_id=str(history.group_id),
        agency_id=agency_id,
        user_id=actor.id,
        actor_email=actor.email,
        metadata={
            **dict(history.artifact_metadata or {}),
            "export_history_id": str(history.id),
            "export_mode": history.export_mode,
            "baseline_export_id": str(history.baseline_export_id)
            if history.baseline_export_id
            else None,
            "total_available_count": history.total_available_count,
            "submission_count": history.exported_count,
            "pending_recipient_count": history.pending_recipient_count,
        },
    )
    return True
