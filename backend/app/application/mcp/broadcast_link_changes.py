"""Revision-fenced insert-only group/broadcast association operation."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.application.mcp.broadcast_link_plan import BroadcastLinkPlan, prepare_link_plan
from app.application.mcp.broadcast_link_source import (
    BroadcastLinkSource,
    link_source_revision,
    load_link_source,
)
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.models import ClientGroupWhatsAppBroadcastLinkModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    prepare_private_delivery_identity_mutation,
)


@dataclass(frozen=True, slots=True)
class BroadcastLinkCommand:
    agency_id: uuid.UUID
    group_id: uuid.UUID
    broadcast_id: uuid.UUID
    matching_field_keys: list[str] | None
    expected_revision: str | None = None


MatchingValidator = Callable[[BroadcastLinkSource, list[str] | None], list[str] | None]


async def inspect_link_addition(
    context: MCPDatabaseContext, command: BroadcastLinkCommand, validate_matching: MatchingValidator
) -> dict[str, Any]:
    source = await load_link_source(
        context,
        agency_id=command.agency_id,
        group_id=command.group_id,
        broadcast_id=command.broadcast_id,
    )
    fields = validate_matching(source, command.matching_field_keys)
    plan = prepare_link_plan(source, fields)
    return {
        "agency_id": str(command.agency_id),
        "group_id": str(command.group_id),
        "broadcast_id": str(command.broadcast_id),
        "source_revision": link_source_revision(source),
        "group_name": source.group.name[:160],
        "broadcast_name": source.broadcast.name[:160],
        "outcome": "existing" if source.existing_link else "would_add",
        "matching_field_keys": fields,
        "source_row_count": source.snapshot["total_submissions"],
        "source_contact_additions": len(plan.contacts),
        "recipient_additions": len(plan.recipients),
        "retained_shared_destinations": len(plan.retained_recipients),
        "shared_source_phone_count": source.snapshot["shared_phone_count"],
        "source_issues": source.snapshot["excluded_counts"],
        "retained_link_count": len(source.links),
        "mobile_identity_additions": 0
        if source.mobile is None
        else len(
            {row.passenger_submission_id for row in source.mobile.plan.candidates}
            - {row.passenger_submission_id for row in source.mobile.existing}
        ),
        "content_trust": "untrusted_business_data",
        "completeness": "complete",
        "notice": "No messages are sent. Every existing link, recipient, override, private delivery and mobile session is retained. Current private-delivery guards are rechecked at mutation.",
    }


async def _guard_deliveries(context: MCPDatabaseContext, source: BroadcastLinkSource) -> None:
    for scope in ({"group_id": source.group.id}, {"broadcast_group_ids": {source.broadcast.id}}):
        try:
            await prepare_private_delivery_identity_mutation(
                context.session,
                agency_id=source.group.agency_id,
                cancel_queued=False,
                cancellation_reason="Additive broadcast link cannot cancel queued private delivery",
                **scope,
            )
        except PrivateDeliveryMutationBlocked as exc:
            raise MCPOperationError("broadcast_link_private_delivery_pending") from exc


async def _persist(
    context: MCPDatabaseContext, source: BroadcastLinkSource, plan: BroadcastLinkPlan
) -> MCPDatabaseResult:
    existing = source.existing_link
    link = existing or ClientGroupWhatsAppBroadcastLinkModel(
        id=uuid.uuid4(),
        agency_id=source.group.agency_id,
        client_group_id=source.group.id,
        broadcast_group_id=source.broadcast.id,
        created_by_user_id=context.principal.user_id,
        matching_field_keys=plan.matching_fields,
        sync_contacts_from_group=source.group.import_only,
    )
    mobile_created = 0
    if existing is None:
        await _guard_deliveries(context, source)
        context.session.add_all([link, *plan.recipients])
        await context.session.flush()
        context.session.add_all(plan.contacts)
        await context.session.flush()
        if source.mobile is not None:
            mobile_created = await source.mobile.apply(context.session, context.principal.user_id)
        # Add only newly discovered field metadata. Existing values are retained.
        source.broadcast.imported_field_keys = sorted(
            set(source.broadcast.imported_field_keys or [])
            | {key for row in plan.contacts for key in row.imported_fields}
        )
        await context.session.flush()
    data = {
        "agency_id": str(source.group.agency_id),
        "group_id": str(source.group.id),
        "broadcast_id": str(source.broadcast.id),
        "link_id": str(link.id),
        "matching_field_keys": link.matching_field_keys,
        "sync_contacts_from_group": link.sync_contacts_from_group,
        "outcome": "existing" if existing else "added",
        "source_contacts_added": len(plan.contacts),
        "recipients_added": len(plan.recipients),
        "mobile_identities_added": mobile_created,
        "contact_bindings": [
            {
                "id": str(row.id),
                "source_submission_id": str(row.source_submission_id),
                "recipient_id": str(row.recipient_id) if row.recipient_id else None,
            }
            for row in [*plan.contacts, *plan.retained_contacts]
        ],
        "recipient_ids": [str(row.id) for row in [*plan.recipients, *plan.retained_recipients]],
    }
    audit = await AuditLogRepository(context.session).record(
        action="application_broadcast_link_added",
        entity_type="client_group",
        entity_id=str(source.group.id),
        agency_id=source.group.agency_id,
        user_id=context.principal.user_id,
        metadata={"mcp_operation_id": str(context.operation_id), **data},
    )
    data["business_audit_id"] = str(audit.id)
    return MCPDatabaseResult(
        data,
        created_entities=()
        if existing
        else (
            MCPCreatedEntity(
                "group_broadcast_link", str(link.id), f"/passports/groups/{source.group.id}"
            ),
        ),
    )


async def _authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
    data = receipt["data"]
    source = await load_link_source(
        context,
        agency_id=uuid.UUID(data["agency_id"]),
        group_id=uuid.UUID(data["group_id"]),
        broadcast_id=uuid.UUID(data["broadcast_id"]),
    )
    link = source.existing_link
    if (
        link is None
        or str(link.id) != data["link_id"]
        or link.matching_field_keys != data["matching_field_keys"]
        or link.sync_contacts_from_group != data["sync_contacts_from_group"]
    ):
        raise MCPOperationError("broadcast_link_receipt_unavailable")
    contacts = {
        (
            str(row.id),
            str(row.source_submission_id),
            str(row.recipient_id) if row.recipient_id else None,
        )
        for row in source.contacts
        if row.source_group_id == source.group.id
    }
    expected = {
        (row["id"], row["source_submission_id"], row["recipient_id"])
        for row in data["contact_bindings"]
    }
    if not expected <= contacts:
        raise MCPOperationError("broadcast_link_receipt_unavailable")
    active = {
        str(row.id)
        for row in source.recipients
        if row.removed_at is None
        and row.merged_into_recipient_id is None
        and row.suppressed_by_roster_resolution_id is None
    }
    if not set(data["recipient_ids"]) <= active:
        raise MCPOperationError("broadcast_link_receipt_unavailable")


def broadcast_link_operation(
    validate: Callable[[dict[str, Any]], BroadcastLinkCommand], validate_matching: MatchingValidator
) -> MCPDatabaseOperation:
    async def add(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = validate(payload)
        source = await load_link_source(
            context,
            agency_id=command.agency_id,
            group_id=command.group_id,
            broadcast_id=command.broadcast_id,
        )
        if link_source_revision(source) != command.expected_revision:
            raise MCPOperationError("broadcast_link_revision_changed")
        plan = prepare_link_plan(source, validate_matching(source, command.matching_field_keys))
        return await _persist(context, source, plan)

    return MCPDatabaseOperation(
        MCPToolPolicy(
            "add_group_broadcast_link",
            MCPCapability.CHANGE,
            frozenset({"add_broadcast_link", "add_source_contacts", "add_mobile_identities"}),
        ),
        add,
        _authorize_receipt,
    )
