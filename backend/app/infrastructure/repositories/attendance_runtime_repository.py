"""Coordinator runtime registration and session-participation persistence."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.mobile_jwt import hash_mobile_lookup
from app.infrastructure.database.models import (
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionRuntimeParticipantModel,
)

RuntimeKind = Literal["native_mobile", "pwa", "webview", "legacy_account"]
RuntimeTerminalStatus = Literal["revoked", "expired", "lost", "replaced"]


class AttendanceRuntimeError(RuntimeError):
    """A privacy-safe runtime registration failure."""


@dataclass(frozen=True, slots=True)
class IssuedBrowserRuntime:
    registration: AttendanceRuntimeRegistrationModel
    cookie_secret: str


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class AttendanceRuntimeRepository:
    """Persist opaque runtimes without storing raw installation identifiers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue_browser_runtime(
        self,
        *,
        agency_id: uuid.UUID,
        coordinator_user_id: uuid.UUID,
        runtime_kind: Literal["pwa", "webview"],
        expires_at: datetime,
        now: datetime | None = None,
    ) -> IssuedBrowserRuntime:
        cookie_secret = secrets.token_urlsafe(32)
        registration = await self.register(
            agency_id=agency_id,
            coordinator_user_id=coordinator_user_id,
            runtime_kind=runtime_kind,
            runtime_identifier=cookie_secret,
            expires_at=expires_at,
            now=now,
        )
        return IssuedBrowserRuntime(
            registration=registration,
            cookie_secret=cookie_secret,
        )

    async def ensure_native_runtime(
        self,
        *,
        agency_id: uuid.UUID,
        coordinator_user_id: uuid.UUID,
        mobile_session_id: uuid.UUID,
        expires_at: datetime,
        now: datetime | None = None,
    ) -> AttendanceRuntimeRegistrationModel:
        return await self.register(
            agency_id=agency_id,
            coordinator_user_id=coordinator_user_id,
            runtime_kind="native_mobile",
            runtime_identifier=str(mobile_session_id),
            native_mobile_session_id=mobile_session_id,
            expires_at=expires_at,
            now=now,
        )

    async def register(
        self,
        *,
        agency_id: uuid.UUID,
        coordinator_user_id: uuid.UUID,
        runtime_kind: RuntimeKind,
        runtime_identifier: str,
        expires_at: datetime,
        native_mobile_session_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> AttendanceRuntimeRegistrationModel:
        observed = _utc(now or datetime.now(tz=UTC))
        expiry = _utc(expires_at)
        if expiry <= observed:
            raise AttendanceRuntimeError("Attendance runtime expiry is invalid")
        identifier_hash = hash_mobile_lookup(
            runtime_identifier,
            purpose=f"attendance-runtime-{runtime_kind}",
        )
        statement = (
            pg_insert(AttendanceRuntimeRegistrationModel)
            .values(
                id=uuid.uuid4(),
                agency_id=agency_id,
                coordinator_user_id=coordinator_user_id,
                runtime_kind=runtime_kind,
                runtime_identifier_hash=identifier_hash,
                native_mobile_session_id=native_mobile_session_id,
                status="active",
                registered_at=observed,
                last_seen_at=observed,
                expires_at=expiry,
                revoked_at=None,
                created_at=observed,
                updated_at=observed,
            )
            .on_conflict_do_update(
                constraint="uq_attendance_runtime_identifier",
                set_={
                    "last_seen_at": observed,
                    "expires_at": expiry,
                    "native_mobile_session_id": native_mobile_session_id,
                    "updated_at": observed,
                },
                # A revoked/lost runtime is never silently reactivated. A
                # browser obtains a fresh high-entropy cookie instead.
                where=AttendanceRuntimeRegistrationModel.status == "active",
            )
            .returning(AttendanceRuntimeRegistrationModel)
        )
        registration = (await self._session.execute(statement)).scalar_one_or_none()
        if registration is None:
            raise AttendanceRuntimeError("Attendance runtime is not active")
        await self._session.flush()
        return registration

    async def resolve_browser_runtime(
        self,
        *,
        agency_id: uuid.UUID,
        coordinator_user_id: uuid.UUID,
        cookie_secret: str,
        runtime_kind: Literal["pwa", "webview"],
        now: datetime | None = None,
        lock: bool = False,
    ) -> AttendanceRuntimeRegistrationModel:
        observed = _utc(now or datetime.now(tz=UTC))
        identifier_hash = hash_mobile_lookup(
            cookie_secret,
            purpose=f"attendance-runtime-{runtime_kind}",
        )
        statement = select(AttendanceRuntimeRegistrationModel).where(
            AttendanceRuntimeRegistrationModel.agency_id == agency_id,
            AttendanceRuntimeRegistrationModel.coordinator_user_id == coordinator_user_id,
            AttendanceRuntimeRegistrationModel.runtime_kind == runtime_kind,
            AttendanceRuntimeRegistrationModel.runtime_identifier_hash == identifier_hash,
            AttendanceRuntimeRegistrationModel.status == "active",
            AttendanceRuntimeRegistrationModel.expires_at > observed,
        )
        if lock:
            statement = statement.with_for_update()
        registration = (await self._session.execute(statement)).scalar_one_or_none()
        if registration is None:
            raise AttendanceRuntimeError("Attendance runtime is unavailable")
        registration.last_seen_at = observed
        registration.updated_at = observed
        await self._session.flush()
        return registration

    async def mark_participation(
        self,
        *,
        agency_id: uuid.UUID,
        session_id: uuid.UUID,
        coordinator_user_id: uuid.UUID,
        runtime_registration_id: uuid.UUID,
        source: Literal["scan", "checkpoint", "discard", "legacy"],
        occurred_at: datetime | None = None,
    ) -> None:
        observed = _utc(occurred_at or datetime.now(tz=UTC))
        await self._session.execute(
            pg_insert(AttendanceSessionRuntimeParticipantModel)
            .values(
                id=uuid.uuid4(),
                agency_id=agency_id,
                session_id=session_id,
                coordinator_user_id=coordinator_user_id,
                runtime_registration_id=runtime_registration_id,
                participation_source=source,
                first_participated_at=observed,
                last_participated_at=observed,
            )
            .on_conflict_do_update(
                constraint="uq_attendance_session_runtime_participant",
                set_={
                    "last_participated_at": observed,
                    "participation_source": source,
                },
            )
        )
        await self._session.flush()

    async def revoke(
        self,
        *,
        registration_id: uuid.UUID,
        agency_id: uuid.UUID,
        coordinator_user_id: uuid.UUID,
        reason: str,
        status: RuntimeTerminalStatus = "revoked",
        replacement_runtime_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> AttendanceRuntimeRegistrationModel:
        normalized_reason = " ".join(reason.split())
        if not (3 <= len(normalized_reason) <= 80):
            raise AttendanceRuntimeError("Attendance runtime revocation reason is invalid")
        registration = (
            await self._session.execute(
                select(AttendanceRuntimeRegistrationModel)
                .where(
                    AttendanceRuntimeRegistrationModel.id == registration_id,
                    AttendanceRuntimeRegistrationModel.agency_id == agency_id,
                    AttendanceRuntimeRegistrationModel.coordinator_user_id == coordinator_user_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if registration is None:
            raise AttendanceRuntimeError("Attendance runtime is unavailable")
        if registration.status == "active":
            observed = _utc(now or datetime.now(tz=UTC))
            registration.status = status
            registration.revoked_at = observed
            registration.revoke_reason = normalized_reason
            registration.replaced_by_runtime_id = replacement_runtime_id
            registration.updated_at = observed
            await self._session.flush()
        elif registration.status != status:
            raise AttendanceRuntimeError("Attendance runtime state conflict")
        return registration


__all__ = [
    "AttendanceRuntimeError",
    "AttendanceRuntimeRepository",
    "IssuedBrowserRuntime",
    "RuntimeKind",
    "RuntimeTerminalStatus",
]
