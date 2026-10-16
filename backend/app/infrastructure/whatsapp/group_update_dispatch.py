"""Revalidate version-two group audiences without affecting legacy queued updates."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_updates import GroupUpdateContact, GroupUpdateFilters
from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.infrastructure.repositories.passport_whatsapp_comparison_cache import (
    PassportWhatsAppComparisonCache,
)
from app.infrastructure.whatsapp.group_update_audience import load_group_update_audience


@dataclass
class GroupUpdateDispatchCache:
    """Reuse locked audience rows in one transaction, matching inputs per slice."""

    comparison_cache: PassportWhatsAppComparisonCache = field(
        default_factory=PassportWhatsAppComparisonCache
    )
    audiences: dict[
        tuple[uuid.UUID, uuid.UUID, GroupUpdateFilters], list[GroupUpdateContact]
    ] = field(default_factory=dict)

    def start_wave(self) -> None:
        """Call before a new source-lock transaction; eligibility is reread."""
        self.audiences.clear()


async def group_update_source_decision(
    session: AsyncSession, log: WhatsAppMessageLogModel,
    *, cache: GroupUpdateDispatchCache | None = None,
) -> tuple[str, str | None]:
    try:
        context = log.document_update_context
        if not isinstance(context, dict) or context.get("audience_version") != 2:
            raise ValueError("Unknown audience version")
        group_id = uuid.UUID(context["group_id"])
        filters = GroupUpdateFilters(**context["filters"])
        raw_keys = context["audience_keys"]
        if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= 1500:
            raise ValueError("Invalid audience")
        keys = set(raw_keys)
        if any(not isinstance(key, str) for key in keys):
            raise ValueError("Invalid contact key")
    except (KeyError, TypeError, ValueError, AttributeError):
        return "failed", "UPDATE_CONTEXT_INVALID: Review the update audience before sending."
    scope = log.agency_id, group_id, filters
    if cache is not None and scope in cache.audiences:
        rows = cache.audiences[scope]
    else:
        rows = await load_group_update_audience(
            session, agency_id=log.agency_id, group_id=group_id, filters=filters, lock=True,
            comparison_cache=cache.comparison_cache if cache is not None else None,
        )
        if cache is not None:
            cache.audiences[scope] = rows
    selected = [row for row in rows if row.audience_key in keys]
    if (len(selected) != len(keys) or any(row.reason for row in selected)
            or any(row.phone_number != log.normalized_phone_number for row in selected)
            or not any(row.recipient_id == log.recipient_id and row.broadcast_group_id == log.broadcast_group_id
                       for row in selected)):
        return "skipped", "UPDATE_AUDIENCE_CHANGED: Submission, document status, contact or broadcast membership changed. Review a fresh preview."
    return "processing", None
