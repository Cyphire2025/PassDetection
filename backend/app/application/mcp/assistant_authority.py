"""Private dashboard-session authority for the first-party AI assistant.

The retained row supplies existing receipt/artifact foreign keys. It is not an
OAuth client grant: its ID is the authenticated dashboard session ID, and every
use rechecks that session, identity, AI settings and the ordinary MCP ceilings.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import MCPAuthError, utc
from app.core.config.settings import Settings
from app.domain.assistant_identity import ASSISTANT_CLIENT_ID as ASSISTANT_CLIENT_ID
from app.domain.entities.entities import User, UserRole
from app.domain.mcp_policy import CAPABILITIES
from app.domain.mcp_section_permissions import SUPPORTED_WRITE_SECTIONS, WRITE_CAPABILITIES
from app.infrastructure.assistant.settings_store import SETTINGS_KEY, load_snapshot
from app.infrastructure.database.dashboard_session_models import DashboardSessionModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.models import PlatformSettingModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


def validate_assistant_claims(user: User, claims: Any) -> datetime:
    """Accept only claims already verified by dashboard HTTP/WebSocket auth."""
    if not isinstance(claims, dict):
        raise MCPAuthError("assistant_mfa_required", 403)
    methods, value = claims.get("amr"), claims.get("mfa_at")
    if (claims.get("sub") != str(user.id) or type(claims.get("sv")) is not int
            or claims["sv"] != user.session_version or not isinstance(methods, list)
            or not any(method in {"totp", "recovery_code"} for method in methods if isinstance(method, str))
            or type(value) not in {int, float} or type(value) is float and not math.isfinite(value)):
        raise MCPAuthError("assistant_mfa_required", 403)
    try:
        UUID(claims["sid"])
        timestamp = cast(int | float, value)
        verified_at = datetime.fromtimestamp(timestamp, UTC)
    except (KeyError, TypeError, ValueError, OverflowError, OSError, AttributeError):
        raise MCPAuthError("assistant_mfa_required", 403) from None
    if timestamp <= 0 or (verified_at - datetime.now(UTC)).total_seconds() > 60:
        raise MCPAuthError("assistant_mfa_required", 403)
    return verified_at


async def _session_authority(
    session: AsyncSession, user_id: UUID, session_version: int, session_id: UUID, *, lock: bool,
) -> DashboardSessionModel:
    statement = select(DashboardSessionModel).where(
        DashboardSessionModel.id == session_id, DashboardSessionModel.user_id == user_id,
        DashboardSessionModel.session_version == session_version,
        DashboardSessionModel.revoked_at.is_(None), DashboardSessionModel.expires_at > datetime.now(UTC),
    ).execution_options(populate_existing=True)
    if lock:
        statement = statement.with_for_update(read=True)
    row = await session.scalar(statement)
    if row is None:
        raise MCPAuthError("invalid_token", 401)
    return row


async def require_assistant_settings(
    session: AsyncSession, *, capability: str | None = None, lock: bool = True,
) -> None:
    statement = select(PlatformSettingModel).where(PlatformSettingModel.key == SETTINGS_KEY)
    if lock:
        statement = statement.with_for_update(read=True)
    # Refresh cached ORM values before loading the validated configuration.
    await session.scalar(statement.execution_options(populate_existing=True))
    snapshot = await load_snapshot(session)
    if not snapshot.configuration.enabled:
        raise MCPAuthError("assistant_access_denied", 403)
    if capability in WRITE_CAPABILITIES and not snapshot.configuration.mcp_write_enabled:
        raise MCPAuthError("write_access_denied", 403)


async def require_assistant_grant(
    session: AsyncSession, settings: Settings, grant: MCPGrantModel, *, lock: bool = False,
) -> None:
    """Additional live checks for internal rows, including delayed worker use."""
    if grant.client_id != ASSISTANT_CLIENT_ID or grant.resource != settings.mcp.resource:
        raise MCPAuthError()
    await lock_assistant_authority(session, settings, grant.user_id, grant.security_version, grant.id)


async def lock_assistant_authority(
    session: AsyncSession, settings: Settings, user_id: UUID, session_version: int, session_id: UUID,
) -> DashboardSessionModel:
    """Match browser logout/rotation's identity -> dashboard-session lock order.

    Call this before acquiring the private grant lock. Repeating checks inside
    the same transaction is safe because these shared authority locks are held.
    """
    from app.application.mcp.authorization import MCPAuthorizationService

    await require_assistant_settings(session)
    auth = MCPAuthorizationService(session, settings)
    await auth.require_enabled(lock=True)
    await auth.require_identity(user_id, session_version, lock=True)
    return await _session_authority(session, user_id, session_version, session_id, lock=True)


async def validate_assistant_authority(
    session: AsyncSession, settings: Settings, user: User, claims: Any,
) -> DashboardSessionModel:
    """Validate discovery without creating authority, tokens or connections."""
    validate_assistant_claims(user, claims)
    if (user.role != UserRole.SUPER_ADMIN or user.actual_role not in {None, user.role}
            or user.actual_agency_id is not None and user.actual_agency_id != user.agency_id):
        raise MCPAuthError("assistant_access_denied", 403)
    authority = await lock_assistant_authority(session, settings, user.id, user.session_version, UUID(claims["sid"]))
    existing = await session.scalar(select(MCPGrantModel).where(MCPGrantModel.id == authority.id)
                                    .execution_options(populate_existing=True))
    if existing is not None and (
        existing.client_id != ASSISTANT_CLIENT_ID or existing.user_id != user.id
        or existing.security_version != user.session_version or existing.enabled is not True
        or existing.revoked_at is not None or utc(existing.expires_at) <= datetime.now(UTC)
        or existing.resource != settings.mcp.resource
    ):
        raise MCPAuthError("assistant_access_denied", 403)
    return authority


async def ensure_assistant_authority(
    session: AsyncSession, settings: Settings, user: User, claims: Any,
) -> MCPGrantModel:
    """Materialize one private identity per live dashboard session; caller commits."""
    from app.application.mcp.authorization import MCPAuthorizationService

    authority = await validate_assistant_authority(session, settings, user, claims)
    verified_at, now = validate_assistant_claims(user, claims), datetime.now(UTC)
    dialect = session.get_bind().dialect.name
    insert = postgres_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
    if insert is None:
        raise MCPAuthError("temporarily_unavailable", 503)
    created = await session.scalar(insert(MCPGrantModel).values(
        id=authority.id, user_id=user.id, client_id=ASSISTANT_CLIENT_ID,
        name="First-party AI assistant", resource=settings.mcp.resource,
        capabilities=sorted(CAPABILITIES), enabled=True, read_enabled=True, write_enabled=True,
        allowed_read_sections=None, allowed_write_sections=sorted(SUPPORTED_WRITE_SECTIONS),
        security_version=user.session_version, mfa_at=verified_at, created_at=now,
        expires_at=authority.expires_at,
    ).on_conflict_do_nothing(index_elements=[MCPGrantModel.id]).returning(MCPGrantModel.id))
    # A concurrent insert/revocation is rechecked after the common row barrier.
    grant = await MCPAuthorizationService(session, settings).require_grant(authority.id, lock=True)
    if grant.client_id != ASSISTANT_CLIENT_ID or grant.user_id != user.id:
        raise MCPAuthError("assistant_access_denied", 403)
    # Preserve actual MFA age for existing sensitive-operation checks.
    if utc(grant.mfa_at) < verified_at:
        grant.mfa_at = verified_at
    if created is not None:
        await AuditLogRepository(session).record(
            action="assistant.authority.created", entity_type="dashboard_session",
            entity_id=str(authority.id), user_id=user.id, result="success",
            metadata={"surface": "assistant"},
        )
    await session.flush()
    return grant
