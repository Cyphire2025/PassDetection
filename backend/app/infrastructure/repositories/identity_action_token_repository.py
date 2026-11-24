"""One-time workforce actions: account-first locking, expiry and atomic redemption."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.identity_security import (
    active_identity_action_key_id,
    hash_identity_action_token,
    identity_action_token_hash_candidates,
)
from app.infrastructure.database.models import (
    IdentityActionTokenModel,
    IdentityNotificationOutboxModel,
    UserModel,
)


class IdentityActionTokenRepository:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime],
        new_id: Callable[[], uuid.UUID],
    ) -> None:
        self._session = session
        self._clock = clock
        self._new_id = new_id

    async def issue_action_token(
        self,
        *,
        user_id: uuid.UUID,
        purpose: str,
        expires_in: timedelta,
        created_by_user_id: uuid.UUID | None = None,
        request_ip_hash: str | None = None,
        now: datetime | None = None,
    ) -> tuple[IdentityActionTokenModel, str]:
        active_now = now or self._clock()
        # Serialize issuance on the durable account row before inspecting the
        # partial-unique active-token set.  Locking only existing token rows is
        # insufficient when two first-time requests both observe an empty set.
        await self._session.flush()
        user_exists = (
            await self._session.execute(
                select(UserModel.id).where(UserModel.id == user_id).with_for_update()
            )
        ).scalar_one_or_none()
        if user_exists is None:
            raise ValueError("Cannot issue an identity action for a missing account")
        active_tokens = (
            (
                await self._session.execute(
                    select(IdentityActionTokenModel)
                    .where(
                        IdentityActionTokenModel.user_id == user_id,
                        IdentityActionTokenModel.purpose == purpose,
                        IdentityActionTokenModel.consumed_at.is_(None),
                        IdentityActionTokenModel.invalidated_at.is_(None),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for active_token in active_tokens:
            active_token.invalidated_at = active_now
        if active_tokens:
            # Flush the invalidation before inserting the replacement so the
            # active-token partial unique index remains a fail-closed race gate.
            await self._session.flush()
            # A superseded one-time credential must not remain queued for
            # delivery after it can no longer be redeemed.  A worker that was
            # already past its external provider boundary may still deliver an
            # unusable link (at-least-once delivery), but its durable row can no
            # longer be reclaimed or reported as current.
            await self._session.execute(
                update(IdentityNotificationOutboxModel)
                .where(
                    IdentityNotificationOutboxModel.action_token_id.in_(
                        [token.id for token in active_tokens]
                    ),
                    IdentityNotificationOutboxModel.status.in_(("pending", "running")),
                )
                .values(
                    status="dead_letter",
                    lease_expires_at=None,
                    last_error_code="superseded",
                    updated_at=active_now,
                )
            )
        raw_token = secrets.token_urlsafe(32)
        row = IdentityActionTokenModel(
            id=self._new_id(),
            user_id=user_id,
            purpose=purpose,
            token_key_id=active_identity_action_key_id(),
            token_hash=hash_identity_action_token(raw_token, purpose=purpose),
            expires_at=active_now + expires_in,
            created_by_user_id=created_by_user_id,
            request_ip_hash=request_ip_hash,
            created_at=active_now,
        )
        self._session.add(row)
        await self._session.flush()
        return row, raw_token

    async def get_valid_action_token(
        self,
        *,
        raw_token: str,
        purpose: str,
        now: datetime | None = None,
    ) -> IdentityActionTokenModel | None:
        active_now = now or self._clock()
        candidates = identity_action_token_hash_candidates(
            raw_token,
            purpose=purpose,
        )
        key_predicates = tuple(
            and_(
                IdentityActionTokenModel.token_key_id == key_id,
                IdentityActionTokenModel.token_hash == token_hash,
            )
            for key_id, token_hash in candidates
        )
        if not key_predicates:
            return None
        eligible = and_(
            IdentityActionTokenModel.purpose == purpose,
            IdentityActionTokenModel.consumed_at.is_(None),
            IdentityActionTokenModel.invalidated_at.is_(None),
            or_(*key_predicates),
        )
        user_id = await self._session.scalar(
            select(IdentityActionTokenModel.user_id).where(
                eligible,
                IdentityActionTokenModel.expires_at > active_now,
            )
        )
        if user_id is None:
            return None
        # Issuance and account/factor fencing lock the account before tokens.
        # Observe the owner without a token lock, then revalidate after waiting.
        user_exists = await self._session.scalar(
            select(UserModel.id).where(UserModel.id == user_id).with_for_update()
        )
        if user_exists is None:
            return None
        active_now = now or self._clock()
        return (
            await self._session.execute(
                select(IdentityActionTokenModel)
                .where(
                    eligible,
                    IdentityActionTokenModel.user_id == user_id,
                    IdentityActionTokenModel.expires_at > active_now,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def consume_action_token(
        self,
        *,
        token_id: uuid.UUID,
        purpose: str,
        now: datetime | None = None,
    ) -> bool:
        """Atomically consume one still-valid action token.

        ``get_valid_action_token`` already locks the PostgreSQL row, but the
        validity predicates belong in the final mutation as a second boundary.
        This protects alternate database/test runtimes that do not implement
        ``FOR UPDATE`` and makes concurrent redemption correctness explicit.
        """

        active_now = now or self._clock()
        result = await self._session.execute(
            update(IdentityActionTokenModel)
            .where(
                IdentityActionTokenModel.id == token_id,
                IdentityActionTokenModel.purpose == purpose,
                IdentityActionTokenModel.expires_at > active_now,
                IdentityActionTokenModel.consumed_at.is_(None),
                IdentityActionTokenModel.invalidated_at.is_(None),
            )
            .values(consumed_at=active_now)
            .returning(IdentityActionTokenModel.id)
            .execution_options(synchronize_session=False)
        )
        return result.scalar_one_or_none() is not None
