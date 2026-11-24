"""Contact duplicate policy and transaction-scoped PostgreSQL serialization."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.phone_number import normalize_phone_number, phone_storage_variants
from app.infrastructure.database.models import PassportSubmissionModel


async def exists_contact_in_group(
    session: AsyncSession,
    group_id: uuid.UUID,
    *,
    client_email: str | None,
    client_phone: str | None,
    exclude_submission_id: uuid.UUID | None = None,
    scope: Literal["group", "platform"] = "group",
    additional_emails: Sequence[str] = (),
    additional_phones: Sequence[str] = (),
) -> bool:
    emails = tuple(dict.fromkeys(value for value in (client_email, *additional_emails) if value))
    phones = tuple(
        dict.fromkeys(
            normalize_phone_number(value) or value
            for value in (client_phone, *additional_phones)
            if value
        )
    )
    if not emails and not phones:
        return False
    if scope not in {"group", "platform"}:
        raise ValueError("Unsupported duplicate contact scope")

    # Different submissions can otherwise pass the read-before-write check
    # concurrently. Transaction-scoped PostgreSQL advisory locks serialize
    # normalized contacts without requiring global lock rows.
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        lock_scope = str(group_id) if scope == "group" else "platform"
        for contact in sorted((*emails, *phones)):
            digest = hashlib.blake2b(
                f"passport-contact:{lock_scope}:{contact}".encode("utf-8"),
                digest_size=8,
            ).digest()
            lock_key = int.from_bytes(digest, "big", signed=True)
            await session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    contact_filters: list[Any] = []
    if emails:
        contact_filters.extend(
            (
                PassportSubmissionModel.client_email.in_(emails),
                PassportSubmissionModel.family_head_email.in_(emails),
            )
        )
    if phones:
        # Canonicalize locks while recognizing values saved by older
        # versions; never rewrite existing/frozen delivery destinations.
        stored_phones = {variant for phone in phones for variant in phone_storage_variants(phone)}
        contact_filters.extend(
            (
                PassportSubmissionModel.client_phone.in_(stored_phones),
                PassportSubmissionModel.family_head_phone.in_(stored_phones),
            )
        )
    stmt = select(PassportSubmissionModel.id).where(or_(*contact_filters))
    if scope == "group":
        stmt = stmt.where(PassportSubmissionModel.group_id == group_id)
    if exclude_submission_id:
        stmt = stmt.where(PassportSubmissionModel.id != exclude_submission_id)
    result = await session.execute(stmt.limit(1))
    return result.scalar_one_or_none() is not None
