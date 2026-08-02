"""Fail-closed recipient checks shared by private document and QR delivery."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientForComparison,
    SubmissionForComparison,
    compare_group_submissions,
)
from app.domain.entities.entities import OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    DocumentWhatsAppDeliveryModel,
    PassengerQrWhatsAppDeliveryModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)

PRIVATE_DELIVERY_ACTIVE_STATUSES = frozenset(
    {"queued", "processing", "delivery_unknown"}
)
PRIVATE_DELIVERY_MUTATION_BLOCKED = (
    "A private WhatsApp delivery is already in progress or has an unknown "
    "outcome. Review it before changing recipients or linked broadcasts."
)
PRIVATE_DELIVERY_RECIPIENT_CHANGED = (
    "The WhatsApp recipient mapping changed after queueing. Refresh the "
    "preview before sending this private item."
)


class PrivateDeliveryMutationBlocked(RuntimeError):
    """Raised when an identity mutation could redirect an active delivery."""


@dataclass(frozen=True, slots=True)
class PrivateDeliveryRecipientValidation:
    allowed: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PrivateDeliveryGroupSourceSnapshot:
    """Immutable mappings protected by one batch-level source transaction."""

    agency_id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    allowed_destinations: frozenset[
        tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]
    ]

    def allows(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        passenger_id: uuid.UUID | None,
        broadcast_group_id: uuid.UUID | None,
        recipient_id: uuid.UUID | None,
        normalized_phone_number: str,
    ) -> bool:
        if (
            agency_id != self.agency_id
            or group_id != self.group_id
            or passenger_id is None
            or broadcast_group_id is None
            or recipient_id is None
        ):
            return False
        return (
            passenger_id,
            recipient_id,
            broadcast_group_id,
            normalized_phone_number,
        ) in self.allowed_destinations


async def lock_private_delivery_group_source_snapshot(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> PrivateDeliveryGroupSourceSnapshot | None:
    """Exclusively freeze one group's authoritative private-delivery identity."""

    group_result = await session.execute(
        select(ClientGroupModel)
        .where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.deleted_at.is_(None),
        )
        .with_for_update()
    )
    group = group_result.scalar_one_or_none()
    if group is None:
        return None

    linked_result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel,
            WhatsAppBroadcastGroupModel,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            and_(
                WhatsAppBroadcastGroupModel.id
                == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
                WhatsAppBroadcastGroupModel.agency_id == agency_id,
            ),
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        )
        .order_by(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
        .with_for_update()
    )
    locked_broadcasts: dict[uuid.UUID, WhatsAppBroadcastGroupModel] = {
        broadcast.id: broadcast for _link, broadcast in linked_result.all()
    }
    eligible_broadcasts: dict[uuid.UUID, str] = {
        broadcast_id: broadcast.name
        for broadcast_id, broadcast in locked_broadcasts.items()
        if broadcast.recipient_opt_in_confirmed_at is not None
    }

    recipient_rows: list[WhatsAppBroadcastRecipientModel] = []
    if locked_broadcasts:
        recipient_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel)
            .where(
                WhatsAppBroadcastRecipientModel.agency_id == agency_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(
                    list(locked_broadcasts)
                ),
            )
            .order_by(
                WhatsAppBroadcastRecipientModel.broadcast_group_id,
                WhatsAppBroadcastRecipientModel.id,
            )
            .with_for_update()
        )
        recipient_rows = list(recipient_result.scalars().all())

    submissions_result = await session.execute(
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
        )
        .order_by(PassportSubmissionModel.id)
        .with_for_update()
    )
    locked_submissions = list(submissions_result.scalars().all())
    submissions = [
        submission
        for submission in locked_submissions
        if submission.status in OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
    ]
    comparison_recipients = [
        RecipientForComparison(
            id=recipient.id,
            broadcast_id=recipient.broadcast_group_id,
            broadcast_name=eligible_broadcasts[recipient.broadcast_group_id],
            name=recipient.name,
            phone=recipient.normalized_phone_number,
            updated_at=recipient.created_at,
            imported_fields=dict(recipient.imported_fields or {}),
        )
        for recipient in recipient_rows
        if (
            recipient.broadcast_group_id in eligible_broadcasts
            and recipient.removed_at is None
            and recipient.suppressed_by_roster_resolution_id is None
        )
    ]
    comparison_submissions = [
        SubmissionForComparison(
            id=submission.id,
            name=submission.client_name,
            client_phone=submission.client_phone,
            family_head_phone=submission.family_head_phone,
            updated_at=submission.updated_at,
            client_email=submission.client_email,
            family_head_email=submission.family_head_email,
            confirmed_fields=dict(submission.confirmed_fields or {}),
            extracted_fields=dict(submission.extracted_fields or {}),
            staff_metadata=dict(submission.staff_metadata or {}),
        )
        for submission in submissions
    ]
    rows, _summary = await asyncio.to_thread(
        compare_group_submissions,
        comparison_recipients,
        comparison_submissions,
    )
    recipients_by_id = {recipient.id: recipient for recipient in recipient_rows}
    allowed_destinations: set[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str]] = set()
    for row in rows:
        if row.status != "submitted" or len(row.submission_ids) != 1:
            continue
        passenger_id = row.submission_ids[0]
        for matched_recipient_id in row.recipient_ids:
            recipient = recipients_by_id.get(matched_recipient_id)
            if recipient is None:
                continue
            allowed_destinations.add(
                (
                    passenger_id,
                    recipient.id,
                    recipient.broadcast_group_id,
                    recipient.normalized_phone_number,
                )
            )
    return PrivateDeliveryGroupSourceSnapshot(
        agency_id=agency_id,
        group_id=group_id,
        group_name=group.name,
        allowed_destinations=frozenset(allowed_destinations),
    )


async def validate_private_delivery_recipient(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    passenger_id: uuid.UUID | None,
    broadcast_group_id: uuid.UUID | None,
    recipient_id: uuid.UUID | None,
    normalized_phone_number: str,
) -> PrivateDeliveryRecipientValidation:
    """Rebuild the exact current identity mapping immediately before send."""

    snapshot = await lock_private_delivery_group_source_snapshot(
        session,
        agency_id=agency_id,
        group_id=group_id,
    )
    if snapshot is None or not snapshot.allows(
        agency_id=agency_id,
        group_id=group_id,
        passenger_id=passenger_id,
        broadcast_group_id=broadcast_group_id,
        recipient_id=recipient_id,
        normalized_phone_number=normalized_phone_number,
    ):
        return PrivateDeliveryRecipientValidation(
            allowed=False,
            reason=PRIVATE_DELIVERY_RECIPIENT_CHANGED,
        )
    return PrivateDeliveryRecipientValidation(allowed=True)


async def prepare_private_delivery_identity_mutation(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID | None = None,
    broadcast_group_ids: set[uuid.UUID] | None = None,
    recipient_ids: set[uuid.UUID] | None = None,
    cancel_queued: bool,
    cancellation_reason: str,
) -> int:
    """Lock active private ledgers, block unsafe states, optionally cancel queues."""

    if broadcast_group_ids is not None and not broadcast_group_ids:
        return 0
    if recipient_ids is not None and not recipient_ids:
        return 0

    document_predicates = [
        DocumentWhatsAppDeliveryModel.agency_id == agency_id,
        DocumentWhatsAppDeliveryModel.status.in_(PRIVATE_DELIVERY_ACTIVE_STATUSES),
    ]
    qr_predicates = [
        PassengerQrWhatsAppDeliveryModel.agency_id == agency_id,
        PassengerQrWhatsAppDeliveryModel.status.in_(PRIVATE_DELIVERY_ACTIVE_STATUSES),
    ]
    if group_id is not None:
        document_predicates.append(DocumentWhatsAppDeliveryModel.group_id == group_id)
        qr_predicates.append(PassengerQrWhatsAppDeliveryModel.group_id == group_id)
    if broadcast_group_ids is not None:
        document_predicates.append(
            DocumentWhatsAppDeliveryModel.broadcast_group_id.in_(broadcast_group_ids)
        )
        qr_predicates.append(
            PassengerQrWhatsAppDeliveryModel.broadcast_group_id.in_(broadcast_group_ids)
        )
    if recipient_ids is not None:
        document_predicates.append(
            DocumentWhatsAppDeliveryModel.recipient_id.in_(recipient_ids)
        )
        qr_predicates.append(
            PassengerQrWhatsAppDeliveryModel.recipient_id.in_(recipient_ids)
        )
    document_result = await session.execute(
        select(DocumentWhatsAppDeliveryModel)
        .where(*document_predicates)
        .order_by(DocumentWhatsAppDeliveryModel.id)
        .with_for_update()
    )
    qr_result = await session.execute(
        select(PassengerQrWhatsAppDeliveryModel)
        .where(*qr_predicates)
        .order_by(PassengerQrWhatsAppDeliveryModel.id)
        .with_for_update()
    )
    locked: list[DocumentWhatsAppDeliveryModel | PassengerQrWhatsAppDeliveryModel] = [
        *document_result.scalars().all(),
        *qr_result.scalars().all(),
    ]

    if any(delivery.status != "queued" for delivery in locked):
        raise PrivateDeliveryMutationBlocked(PRIVATE_DELIVERY_MUTATION_BLOCKED)
    if locked and not cancel_queued:
        raise PrivateDeliveryMutationBlocked(PRIVATE_DELIVERY_MUTATION_BLOCKED)

    now = datetime.now(tz=UTC)
    for delivery in locked:
        delivery.status = "failed"
        delivery.error_message = cancellation_reason[:2000]
        delivery.status_updated_at = now
        delivery.updated_at = now
    return len(locked)
