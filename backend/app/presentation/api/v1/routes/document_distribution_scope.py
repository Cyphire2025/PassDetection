"""Document distribution: scope."""

from __future__ import annotations

import uuid
from typing import cast

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import PassportSubmission, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DocumentDistributionBatchModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.documents.document_matcher import DocumentMatcher, PassengerIdentifier
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.routes.document_distribution_matching import (
    _linked_document_match_identifiers,
    _read_linked_document_match_source,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_match_roster_snapshot,
    _owner_scope_for,
)


async def _get_authorized_group(
    group_id: uuid.UUID,
    *,
    current_user: User,
    session: AsyncSession,
) -> ClientGroupModel:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    statement = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.agency_id == current_user.agency_id,
    )
    statement = AuthorizationPolicy.apply_group_visibility_scope(statement, current_user)
    result = await session.execute(statement)
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    return cast(ClientGroupModel, group)


async def _get_visible_document_batch(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID,
    current_user: User,
) -> DocumentDistributionBatchModel | None:
    """Resolve a batch only through the caller's tenant and group visibility."""

    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        return None
    statement = (
        select(DocumentDistributionBatchModel)
        .join(
            ClientGroupModel,
            ClientGroupModel.id == DocumentDistributionBatchModel.group_id,
        )
        .where(
            DocumentDistributionBatchModel.id == batch_id,
            DocumentDistributionBatchModel.agency_id == current_user.agency_id,
            ClientGroupModel.agency_id == current_user.agency_id,
        )
    )
    statement = AuthorizationPolicy.apply_group_visibility_scope(statement, current_user)
    result = await session.execute(statement)
    return cast(DocumentDistributionBatchModel | None, result.scalar_one_or_none())


async def _lock_active_document_scope(
    session: AsyncSession,
    *,
    current_user: User,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> tuple[UserModel, ClientGroupModel]:
    """Re-fetch and lock the active actor, agency, and group before DB writes."""

    result = await session.execute(
        select(UserModel, ClientGroupModel)
        .select_from(UserModel)
        .join(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .join(ClientGroupModel, ClientGroupModel.agency_id == AgencyModel.id)
        .where(
            UserModel.id == current_user.id,
            UserModel.agency_id == agency_id,
            UserModel.role == current_user.role.value,
            UserModel.is_active.is_(True),
            UserModel.deleted_at.is_(None),
            AgencyModel.id == agency_id,
            AgencyModel.is_active.is_(True),
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account, agency, or group is no longer authorized for this upload.",
        )
    actor, group = row
    try:
        # Authorize with the row that was just re-read under lock, not the
        # request-scoped principal snapshot created before PDF processing.
        await AuthorizationPolicy(session).require_export_data(actor, group)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    return actor, group


async def _lock_document_passenger_roster(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> None:
    """Lock the complete tenant-scoped roster in a deterministic order.

    The parent group is already locked by ``_lock_active_document_scope``.  Its
    row lock serializes new roster inserts through the foreign key, while these
    row locks serialize edits and removals of existing passengers until the
    document-assignment transaction commits.
    """

    await session.execute(
        select(PassportSubmissionModel.id)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
        )
        .order_by(PassportSubmissionModel.id)
        .with_for_update()
    )


def _detach_distribution_batch_before_long_processing(
    session: AsyncSession,
    batch: DocumentDistributionBatchModel,
) -> None:
    """Retain loaded counters across rollback without keeping a transaction open."""

    session.sync_session.expunge(batch)


async def _lock_and_validate_document_match_scope(
    session: AsyncSession,
    *,
    current_user: User,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    matcher: DocumentMatcher,
    expected_roster_snapshot: tuple[tuple[str, ...], ...],
    expected_source_snapshot: tuple[tuple[str, ...], ...],
    expected_supplemental_identifiers: tuple[PassengerIdentifier, ...] | None,
    required_passenger_id: uuid.UUID | None = None,
) -> tuple[UserModel, list[PassportSubmission]]:
    """Lock and revalidate every mutable row that influenced assignment."""

    actor, locked_group = await _lock_active_document_scope(
        session,
        current_user=current_user,
        group_id=group_id,
        agency_id=agency_id,
    )
    current_source = await _read_linked_document_match_source(
        session,
        group=locked_group,
        lock=True,
    )
    await _lock_document_passenger_roster(
        session,
        agency_id=agency_id,
        group_id=group_id,
    )
    current_passengers = await _group_passengers(
        group_id,
        current_user=current_user,
        session=session,
    )
    source_changed = current_source.snapshot != expected_source_snapshot
    roster_changed = _document_match_roster_snapshot(current_passengers) != expected_roster_snapshot
    required_passenger_missing = required_passenger_id is not None and all(
        passenger.id != required_passenger_id for passenger in current_passengers
    )
    identifiers_changed = False
    if not source_changed and not roster_changed and expected_supplemental_identifiers is not None:
        current_identifiers = await _linked_document_match_identifiers(
            session,
            group=locked_group,
            passengers=current_passengers,
            matcher=matcher,
            source=current_source,
        )
        identifiers_changed = current_identifiers != expected_supplemental_identifiers
    if source_changed or roster_changed or required_passenger_missing or identifiers_changed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This group's passenger or linked WhatsApp details changed while "
                "the PDFs were being processed. Review and upload them again."
            ),
        )
    return actor, current_passengers


async def _group_passengers(
    group_id: uuid.UUID,
    *,
    current_user: User,
    session: AsyncSession,
) -> list[PassportSubmission]:
    if not current_user.agency_id:
        return []
    return await PassportSubmissionRepository(session).list_by_group(
        current_user.agency_id,
        group_id,
        limit=5000,
        operational_only=True,
        exclude_archived_groups=True,
        created_by_user_id=_owner_scope_for(current_user),
        visible_to_user=current_user,
    )
