"""Durable email synchronization: mailbox."""

from __future__ import annotations

from sqlalchemy import select

from app.application.interfaces.email_provider import (
    EmailChangeKind,
    EmailProvider,
    EmailProviderResponseError,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.email_integrations.matching import GroupForAssociation
from app.core.config.settings import Settings
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository

from .sync_contracts import EmailRelevanceContext, SyncClaim


async def _load_relevance_context(claim: SyncClaim) -> EmailRelevanceContext:
    """Load a stable, read-only active roster snapshot once per sync run."""

    async with AsyncSessionFactory() as session:
        owner = await UserRepository(session).get_by_id(claim.owner_user_id)
        if owner is None or not owner.is_active:
            return EmailRelevanceContext(groups=(), passengers=())
        groups_stmt = select(ClientGroupModel).where(
            ClientGroupModel.agency_id == claim.agency_id,
            ClientGroupModel.status.notin_({"archived", "deleted"}),
        )
        groups_result = await session.execute(
            AuthorizationPolicy.apply_group_visibility_scope(
                groups_stmt,
                owner,
            )
        )
        groups = tuple(
            GroupForAssociation(
                id=group.id,
                name=group.name,
                token=group.token,
                destination=group.destination,
                travel_date=group.travel_date,
            )
            for group in groups_result.scalars().all()
        )
        passengers = tuple(
            await PassportSubmissionRepository(session).list_by_agency(
                claim.agency_id,
                limit=5_000,
                exclude_archived_groups=True,
                visible_to_user=owner,
            )
        )
    return EmailRelevanceContext(groups=groups, passengers=passengers)


async def _initial_message_ids(
    provider: EmailProvider,
    *,
    access_token: str,
    settings: Settings,
) -> tuple[list[str], str | None]:
    profile = await provider.get_account_profile(access_token=access_token)
    references = await provider.list_messages(
        access_token=access_token,
        lookback_days=settings.email_sync_full_lookback_days,
        max_messages=settings.email_sync_max_messages,
    )
    return (
        list(dict.fromkeys(item.provider_message_id for item in references)),
        profile.history_cursor,
    )


async def _incremental_message_ids(
    provider: EmailProvider,
    *,
    access_token: str,
    start_cursor: str,
    max_messages: int,
) -> tuple[list[str], str]:
    message_ids: list[str] = []
    seen: set[str] = set()
    page_token: str | None = None
    latest_cursor = start_cursor
    for _ in range(1_000):
        page = await provider.list_history_page(
            access_token=access_token,
            start_history_id=start_cursor,
            page_token=page_token,
            max_results=100,
        )
        latest_cursor = page.latest_history_id
        for change in page.changes:
            if change.kind == EmailChangeKind.DELETED:
                continue
            if change.provider_message_id in seen:
                continue
            seen.add(change.provider_message_id)
            message_ids.append(change.provider_message_id)
        if not page.next_page_token:
            break
        if len(message_ids) >= max_messages:
            # Resume at the provider-supplied page boundary instead of
            # advancing to a mailbox-wide latest cursor and skipping pages.
            if page.resume_history_id:
                latest_cursor = page.resume_history_id
            break
        page_token = page.next_page_token
    else:
        raise EmailProviderResponseError(
            "Email history pagination exceeded its safety limit",
            code="EMAIL_PROVIDER_PAGINATION_INVALID",
        )
    return message_ids, latest_cursor
