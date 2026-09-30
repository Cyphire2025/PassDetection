"""Transaction-bound MCP grants and rotation, separate from MCP token verification.

The HTTP adapter commits rejected exchanges too: refresh reuse must durably revoke
the family, not be undone by the request dependency's exception rollback.
"""

from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.client_policy import validate_client, validate_resource
from app.application.mcp.credentials import (
    PKCE_CHALLENGE,
    MCPAuthError,
    credential_hash,
    new_credential,
    pkce_challenge,
    utc,
)
from app.core.config.settings import Settings
from app.domain.mcp_policy import validate_capabilities
from app.infrastructure.database.mcp_models import (
    MCPAuthorizationCodeModel,
    MCPControlModel,
    MCPGrantModel,
    MCPTokenModel,
)
from app.infrastructure.database.models import UserModel, UserSecurityStateModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


@dataclass(frozen=True, slots=True)
class MCPPrincipal:
    grant_id: uuid.UUID
    user_id: uuid.UUID
    client_id: str
    capabilities: tuple[str, ...]
    expires_at: datetime
    resource: str


class MCPAuthorizationService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings

    def digest(self, value: str) -> str:
        return credential_hash(value, self.settings.app_secret_key)

    async def require_enabled(self, *, lock: bool = False) -> None:
        statement = select(MCPControlModel.enabled).where(MCPControlModel.id == 1)
        if lock:
            # A shared row lock allows concurrent application operations while
            # serializing their transaction boundary against emergency disable.
            statement = statement.with_for_update(read=True)
        enabled = await self.session.scalar(statement)
        if not self.settings.mcp.enabled or enabled is not True:
            raise MCPAuthError("temporarily_unavailable", 503)

    def validate_client(self, client_id: str, redirect_uri: str | None = None) -> None:
        validate_client(self.settings.mcp, client_id, redirect_uri)

    def validate_resource(self, resource: str) -> None:
        validate_resource(self.settings.mcp, resource)

    def require_capability(self, grant: MCPGrantModel, capability: str) -> None:
        if capability not in grant.capabilities or capability not in self.settings.mcp.effective_capabilities:
            raise MCPAuthError("insufficient_scope", 403)

    async def require_identity(
        self, user_id: uuid.UUID, security_version: int, *, lock: bool = False
    ) -> None:
        statement = (
            select(UserModel, UserSecurityStateModel)
            .join(UserSecurityStateModel, UserSecurityStateModel.user_id == UserModel.id)
            .where(UserModel.id == user_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update(read=True, of=[UserModel.id, UserSecurityStateModel.user_id])
        row = (await self.session.execute(statement)).first()
        if row is None:
            raise MCPAuthError()
        user, security = row
        if (
            not user.is_active
            or user.deleted_at is not None
            or user.role != "super_admin"
            or security.credential_state != "active"
            or security.session_version != security_version
            or security.mfa_enabled_at is None
        ):
            raise MCPAuthError()

    async def require_grant(self, grant_id: uuid.UUID, *, lock: bool = False) -> MCPGrantModel:
        await self.require_enabled(lock=lock)
        statement = (
            select(MCPGrantModel)
            .where(MCPGrantModel.id == grant_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            statement = statement.with_for_update()
        grant = await self.session.scalar(statement)
        if (
            grant is None
            or grant.revoked_at is not None
            or utc(grant.expires_at) <= datetime.now(UTC)
        ):
            raise MCPAuthError()
        self.validate_client(grant.client_id)
        self.validate_resource(grant.resource)
        await self.require_identity(grant.user_id, grant.security_version, lock=lock)
        return grant

    async def authorize(
        self,
        *,
        user_id: uuid.UUID,
        security_version: int,
        mfa_at: datetime,
        client_id: str,
        redirect_uri: str,
        resource: str,
        challenge: str,
        scopes: list[str],
        name: str,
    ) -> str:
        await self.require_enabled()
        self.validate_client(client_id, redirect_uri)
        self.validate_resource(resource)
        now = datetime.now(UTC)
        if (
            not PKCE_CHALLENGE.fullmatch(challenge)
            or not -60 <= (now - utc(mfa_at)).total_seconds() <= 600
        ):
            raise MCPAuthError("invalid_request")
        try:
            capabilities = validate_capabilities(scopes)
        except ValueError as exc:
            raise MCPAuthError("invalid_scope") from exc
        if set(capabilities) - set(self.settings.mcp.effective_capabilities):
            raise MCPAuthError("invalid_scope")
        await self.require_identity(user_id, security_version)
        grant = MCPGrantModel(
            id=uuid.uuid4(),
            user_id=user_id,
            security_version=security_version,
            client_id=client_id,
            name=name,
            resource=resource,
            capabilities=capabilities,
            mfa_at=mfa_at,
            created_at=now,
            expires_at=now + timedelta(days=7),
        )
        self.session.add(grant)
        await self.session.flush()
        code = new_credential("code")
        self.session.add(
            MCPAuthorizationCodeModel(
                code_hash=self.digest(code),
                grant_id=grant.id,
                redirect_uri=redirect_uri,
                code_challenge=challenge,
                expires_at=now + timedelta(minutes=5),
            )
        )
        await self.audit("authorized", grant)
        await self.session.flush()
        return code

    async def exchange_code(
        self,
        *,
        code: str,
        verifier: str,
        client_id: str,
        redirect_uri: str,
        resource: str,
    ) -> dict[str, str | int]:
        self.validate_client(client_id, redirect_uri)
        self.validate_resource(resource)
        code_row = await self.session.scalar(
            select(MCPAuthorizationCodeModel).where(
                MCPAuthorizationCodeModel.code_hash == self.digest(code),
            )
        )
        if code_row is None:
            raise MCPAuthError()
        # The grant is the common serialization point for code/refresh/revocation.
        grant = await self.require_grant(code_row.grant_id, lock=True)
        await self.session.refresh(code_row)
        now = datetime.now(UTC)
        if (
            code_row.consumed_at is not None
            or utc(code_row.expires_at) <= now
            or grant.client_id != client_id
            or code_row.redirect_uri != redirect_uri
            or not hmac.compare_digest(pkce_challenge(verifier), code_row.code_challenge)
        ):
            raise MCPAuthError()
        consumed = await self.session.scalar(
            update(MCPAuthorizationCodeModel)
            .where(
                MCPAuthorizationCodeModel.code_hash == code_row.code_hash,
                MCPAuthorizationCodeModel.consumed_at.is_(None),
            )
            .values(consumed_at=now)
            .returning(MCPAuthorizationCodeModel.code_hash)
        )
        if consumed is None:
            raise MCPAuthError()
        return await self.issue_pair(grant, now)

    async def refresh(self, *, token: str, client_id: str, resource: str) -> dict[str, str | int]:
        self.validate_client(client_id)
        self.validate_resource(resource)
        token_row = await self.session.scalar(
            select(MCPTokenModel).where(
                MCPTokenModel.token_hash == self.digest(token),
                MCPTokenModel.kind == "refresh",
            )
        )
        if token_row is None:
            raise MCPAuthError()
        grant = await self.require_grant(token_row.grant_id, lock=True)
        await self.session.refresh(token_row)
        now = datetime.now(UTC)
        if grant.client_id != client_id or utc(token_row.expires_at) <= now:
            raise MCPAuthError()
        consumed = await self.session.scalar(
            update(MCPTokenModel)
            .where(
                MCPTokenModel.token_hash == token_row.token_hash,
                MCPTokenModel.consumed_at.is_(None),
            )
            .values(consumed_at=now)
            .returning(MCPTokenModel.token_hash)
        )
        if consumed is None:
            grant.revoked_at = now
            grant.revocation_reason = "refresh_reuse"
            await self.audit("refresh_reuse", grant, denied=True)
            await self.session.flush()
            raise MCPAuthError()
        return await self.issue_pair(grant, now)

    async def issue_pair(self, grant: MCPGrantModel, now: datetime) -> dict[str, str | int]:
        access, refresh = new_credential("access"), new_credential("refresh")
        expires = min(now + timedelta(minutes=15), utc(grant.expires_at))
        for raw, kind, expiry in (
            (access, "access", expires),
            (refresh, "refresh", grant.expires_at),
        ):
            self.session.add(
                MCPTokenModel(
                    token_hash=self.digest(raw),
                    grant_id=grant.id,
                    kind=kind,
                    created_at=now,
                    expires_at=expiry,
                )
            )
        await self.audit("token_issued", grant)
        await self.session.flush()
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": max(0, int((expires - now).total_seconds())),
            "scope": " ".join(capability for capability in grant.capabilities if capability in self.settings.mcp.effective_capabilities),
        }

    async def verify_access(self, token: str, capability: str | None = None) -> MCPPrincipal:
        if not token.startswith("gcmcp_access_") or len(token) > 128:
            raise MCPAuthError("invalid_token", 401)
        token_row = await self.session.scalar(
            select(MCPTokenModel).where(
                MCPTokenModel.token_hash == self.digest(token),
                MCPTokenModel.kind == "access",
            )
        )
        now = datetime.now(UTC)
        if token_row is None or utc(token_row.expires_at) <= now:
            raise MCPAuthError("invalid_token", 401)
        grant = await self.require_grant(token_row.grant_id)
        if capability is not None:
            self.require_capability(grant, capability)
        if grant.last_used_at is None or (now - utc(grant.last_used_at)).total_seconds() >= 60:
            grant.last_used_at = now
            await self.session.flush()
        return MCPPrincipal(
            grant.id,
            grant.user_id,
            grant.client_id,
            tuple(value for value in grant.capabilities if value in self.settings.mcp.effective_capabilities),
            utc(token_row.expires_at),
            grant.resource,
        )

    async def audit(self, action: str, grant: MCPGrantModel, *, denied: bool = False) -> None:
        await AuditLogRepository(self.session).record(
            action=f"mcp.{action}",
            entity_type="mcp_connection",
            entity_id=str(grant.id),
            user_id=grant.user_id,
            result="denied" if denied else "success",
            metadata={"client_id": grant.client_id},
        )
