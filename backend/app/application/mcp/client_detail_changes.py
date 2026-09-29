"""Reviewed sparse contact/detail corrections through the shared website rules."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.client_detail_revisions import preserve_client_detail_revision
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.use_cases.passports.client_details_transaction import (
    ClientDetailsUnavailable,
    apply_client_detail_correction,
    editable_client_submission,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission, User, UserRole
from app.domain.exceptions.exceptions import ValidationError
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.whatsapp.private_delivery_policy import PrivateDeliveryMutationBlocked

CLIENT_DETAIL_POLICY = MCPToolPolicy(
    "correct_client_details",
    MCPCapability.CHANGE,
    frozenset({"correct_client_details_with_history"}),
)
CLIENT_DETAIL_READ_POLICY = MCPToolPolicy(
    "inspect_client_details", MCPCapability.READ, frozenset({"read"})
)


@dataclass(frozen=True, slots=True)
class MCPClientDetailCommand:
    submission_id: uuid.UUID
    expected_updated_at: datetime
    changes: dict[str, Any]


async def _actor(session: AsyncSession, principal: MCPPrincipal) -> User:
    user = await UserRepository(session).get_by_id(principal.user_id)
    if user is None or not user.is_active or user.role != UserRole.SUPER_ADMIN:
        raise MCPAuthError("access_denied", 403)
    return user


async def inspect_client_details(
    session: AsyncSession,
    principal: MCPPrincipal,
    submission_id: uuid.UUID,
) -> tuple[PassportSubmission, ClientGroup]:
    actor = await _actor(session, principal)
    try:
        return await editable_client_submission(submission_id, actor, session, lock=False)
    except ClientDetailsUnavailable as exc:
        raise MCPAuthError("access_denied", 403) from exc


def client_detail_operation(
    validate: Callable[[dict[str, Any]], MCPClientDetailCommand],
) -> MCPDatabaseOperation:
    async def authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        # Creation attribution grants never authorize another connection's replay.
        # The current live grant is checked by the receipt service before this.
        await inspect_client_details(
            context.session, context.principal, uuid.UUID(receipt["data"]["submission_id"])
        )

    async def correct(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = validate(payload)
        actor = await _actor(context.session, context.principal)
        revision_id: uuid.UUID | None = None

        async def preserve(
            before: PassportSubmission,
            after: PassportSubmission,
            _group: ClientGroup,
            changed: tuple[str, ...],
        ) -> None:
            nonlocal revision_id
            revision_id = await preserve_client_detail_revision(
                context.session,
                operation_id=context.operation_id,
                before=before,
                after=after,
                changed_fields=changed,
            )

        try:
            result = await apply_client_detail_correction(
                context.session,
                submission_id=command.submission_id,
                user=actor,
                expected_updated_at=command.expected_updated_at,
                changes=command.changes,
                cancel_queued=False,
                preserve_revision=preserve,
            )
        except ClientDetailsUnavailable as exc:
            if exc.status in {403, 404}:
                raise MCPAuthError("access_denied", 403) from exc
            raise MCPOperationError("client_details_changed_or_unavailable") from exc
        except PrivateDeliveryMutationBlocked as exc:
            raise MCPOperationError("client_details_delivery_pending") from exc
        except ValidationError as exc:
            # Existing validators can include custom field labels. Do not echo
            # those uncontrolled strings into generic failure messages/audits.
            raise MCPOperationError("invalid_client_details") from exc
        return MCPDatabaseResult(
            {
                "submission_id": str(result.submission.id),
                "group_id": str(result.submission.group_id),
                "agency_id": str(result.submission.agency_id),
                "updated_at": result.submission.updated_at.isoformat(),
                "changed_fields": list(result.changed_fields),
                "record_revision_id": str(revision_id) if revision_id else None,
                "path": f"/passports/groups/{result.submission.group_id}",
            }
        )

    return MCPDatabaseOperation(CLIENT_DETAIL_POLICY, correct, authorize_receipt)
