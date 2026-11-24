"""Transactional cleanup for one owner-scoped email connection.

The connection row is the deletion boundary.  This module deliberately removes
only records that can be traced to that connection and only travel documents
that were created by its artifacts and are not referenced by another email
artifact.  Manually uploaded documents and documents reused as duplicates are
preserved.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.email_models import EmailConnectionModel

from .account_removal_plan import _collect_email_account_removal_plan
from .account_removal_records import _delete_email_account_records
from .account_removal_storage import _unreferenced_email_storage_keys


@dataclass(frozen=True)
class EmailAccountRemovalResult:
    """Database cleanup totals and now-unreferenced object-storage keys."""

    connection_id: uuid.UUID
    message_count: int
    artifact_count: int
    review_count: int
    activity_count: int
    document_count: int
    notification_count: int
    audit_log_count: int
    storage_keys: tuple[str, ...]


async def purge_email_connection_records(
    session: AsyncSession, *, connection: EmailConnectionModel
) -> EmailAccountRemovalResult:
    """Remove the selected connection's durable records inside one transaction.

    The caller owns the transaction and must commit before deleting the returned
    object-storage keys.  That ordering avoids leaving live database rows that
    point at missing files when a relational delete fails.
    """

    plan = await _collect_email_account_removal_plan(session, connection=connection)
    counts = await _delete_email_account_records(session, connection=connection, plan=plan)
    storage_keys = await _unreferenced_email_storage_keys(
        session,
        artifact_storage_keys=plan.artifact_storage_keys,
        document_storage_keys=plan.document_storage_keys,
    )
    return EmailAccountRemovalResult(
        connection_id=plan.connection_id,
        message_count=len(plan.message_ids),
        artifact_count=len(plan.artifact_ids),
        review_count=len(plan.review_ids),
        activity_count=counts.activity_count,
        document_count=len(plan.removable_document_ids),
        notification_count=counts.notification_count,
        audit_log_count=counts.audit_log_count,
        storage_keys=storage_keys,
    )
