"""DB-only canonical merges of a reviewed immutable workbook and current roster."""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.application.mcp.contact_uploads import MCPContactUploadService
from app.application.mcp.group_workbook_plan import (
    CHECKPOINT_KEY,
    GroupWorkbookImport,
    GroupWorkbookSupport,
    group_scope,
    import_preview,
    require_native_source,
)
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.core.config.settings import Settings
from app.domain.exceptions.exceptions import ValidationError as BusinessValidationError
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.domain.value_objects.client_collection_provenance import strip_client_collection_provenance
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.mobile_group_capacity import SqlAlchemyGroupPassengerCapacityGuard
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


def group_workbook_definition(
    settings: Settings, support: GroupWorkbookSupport
) -> MCPDatabaseOperation:
    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        try:
            draft = GroupWorkbookImport.model_validate(payload)
        except ValidationError as exc:
            raise MCPOperationError("invalid_group_workbook_import") from exc
        service = MCPContactUploadService(context.session, settings, purpose="group_workbook")
        row = await service.get(context.principal, draft.upload_id, lock=True)
        if row.agency_id != draft.agency_id or not hmac.compare_digest(
            row.sha256, draft.source_sha256
        ):
            raise MCPOperationError("group_workbook_source_changed")
        if row.consumed_operation_id is not None:
            raise MCPOperationError("group_workbook_already_used")
        await require_native_source(context, row, draft.group_id)
        checkpoint = row.workbook_snapshot.get(CHECKPOINT_KEY)
        if not isinstance(checkpoint, dict):
            raise MCPOperationError("group_workbook_source_changed")
        actor, group, resolved, preview = await import_preview(
            context, draft, checkpoint, support=support, mutate=True
        )
        if not hmac.compare_digest(draft.preview_sha256, preview["preview_sha256"]):
            raise MCPOperationError("group_workbook_preview_changed")
        if preview["imported_count"]:
            try:
                await SqlAlchemyGroupPassengerCapacityGuard(context.session).assert_available(
                    agency_id=group.agency_id,
                    group_id=group.id,
                    additional_passengers=preview["imported_count"],
                )
            except BusinessValidationError as exc:
                raise MCPOperationError("group_workbook_group_capacity") from exc
        now, created, changed_ids = datetime.now(UTC), [], []
        for parsed, existing in resolved:
            if existing is not None:
                support.apply(existing, parsed, now=now)
                changed_ids.append(existing.id)
                continue
            identifier = uuid.uuid4()
            submission = PassportSubmissionModel(
                id=identifier,
                group_id=group.id,
                agency_id=group.agency_id,
                client_name=parsed.client_name,
                client_email=parsed.client_email,
                client_phone=parsed.client_phone,
                departure_city=parsed.departure_city,
                nearest_domestic_airport=parsed.nearest_domestic_airport,
                image_s3_key=f"excel-imports/{group.id}/{identifier}.placeholder",
                status="client_submitted",
                confirmed_fields=parsed.confirmed_fields or None,
                extracted_fields=parsed.confirmed_fields or None,
                staff_metadata=strip_client_collection_provenance(parsed.staff_metadata) or None,
                overall_confidence=1.0 if parsed.confirmed_fields else None,
                confidence_score={
                    "source": "excel_import",
                    "row_number": parsed.row_number,
                    "source_sheet": parsed.worksheet_name,
                },
                client_reviewed_at=now,
                created_at=now,
                updated_at=now,
            )
            context.session.add(submission)
            created.append(submission)
            changed_ids.append(identifier)
        if changed_ids:
            await propagate_mobile_passenger_change(
                context.session,
                agency_id=group.agency_id,
                group_id=group.id,
                passenger_submission_ids=changed_ids,
                actor_user_id=actor.id,
                change_kind="profile",
            )
        row.consumed_operation_id, row.consumed_at = context.operation_id, now
        audit = await AuditLogRepository(context.session).record(
            action="passport_group_imported",
            entity_type="client_group",
            entity_id=str(group.id),
            agency_id=group.agency_id,
            user_id=actor.id,
            actor_email=actor.email,
            metadata={
                "imported_count": len(created),
                "updated_count": preview["updated_count"],
                "filename": row.filename,
                "mcp_operation_id": str(context.operation_id),
                "upload_source_id": str(row.id),
                "source_sha256": row.sha256,
                "preview_sha256": preview["preview_sha256"],
            },
        )
        return MCPDatabaseResult(
            {
                "agency_id": str(group.agency_id),
                "group_id": str(group.id),
                "imported_count": len(created),
                "updated_count": preview["updated_count"],
                "skipped_count": preview["skipped_count"],
                "source_rows": preview["source_rows"],
                "upload_source_id": str(row.id),
                "source_sha256": row.sha256,
                "preview_sha256": preview["preview_sha256"],
                "source_retained": True,
                "messages_sent": 0,
                "business_audit_id": str(audit.id),
            },
            created_entities=(
                MCPCreatedEntity(
                    "passport_import", str(context.operation_id), f"/groups/{group.id}"
                ),
            ),
        )

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        data = receipt["data"]
        service = MCPContactUploadService(context.session, settings, purpose="group_workbook")
        await service.authority(context.principal)
        await service.agency(uuid.UUID(data["agency_id"]))
        await group_scope(
            context, uuid.UUID(data["agency_id"]), uuid.UUID(data["group_id"]), support
        )

    return MCPDatabaseOperation(
        MCPToolPolicy(
            "import_group_workbook",
            MCPCapability.CHANGE,
            frozenset(
                {
                    "import_passengers",
                    "update_passenger_profiles",
                    "retain_sources",
                    "mobile_sync",
                    "sync_linked_broadcast_contacts",
                }
            ),
        ),
        mutate,
        authorize,
    )
