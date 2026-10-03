"""Requester capability is separate from dashboard authority and OAuth codes."""

from __future__ import annotations

import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.client_policy import DIRECT_CLIENT_NAMES, validate_authorization_client
from app.application.mcp.credentials import PKCE_CHALLENGE, MCPAuthError, new_credential, utc
from app.application.mcp.permissions import validate_device_permissions
from app.core.config.settings import Settings
from app.domain.mcp_policy import validate_capabilities
from app.infrastructure.database.mcp_models import (
    MCPAuthorizationCodeModel,
    MCPConnectionRequestModel,
    MCPControlModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

REQUEST_TTL = timedelta(minutes=10)
GLOBAL_CREATION_LIMIT = 100
SOURCE_CREATION_LIMIT = 10
ACTIVE_REQUEST_LIMIT = 50


def request_cookie_name(identifier: uuid.UUID) -> str:
    return "gc_mcp_request_" + identifier.hex


def public_request_payload(row: MCPConnectionRequestModel) -> dict[str, object]:
    return {
        "id": str(row.id),
        "status": "expired"
        if row.status in {"pending", "approved"} and utc(row.expires_at) <= datetime.now(UTC)
        else row.status,
        "name": row.name,
        "device_platform": row.device_platform,
        "client_name": DIRECT_CLIENT_NAMES.get(row.client_id, "MCP client"),
        "comparison_code": row.comparison_code,
        "requested_capabilities": row.requested_capabilities,
        "approved_capabilities": row.approved_capabilities,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
    }


def admin_request_payload(row: MCPConnectionRequestModel) -> dict[str, object]:
    return {
        **public_request_payload(row),
        "decided_at": row.decided_at,
        "connection_id": str(row.grant_id) if row.grant_id else None,
    }


class MCPConnectionRequestService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session, self.settings = session, settings
        self.auth = MCPAuthorizationService(session, settings)

    async def create(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        resource: str,
        state: str,
        challenge: str,
        scopes: list[str],
        platform: str,
        source: str,
        resume: dict[uuid.UUID, str],
    ) -> tuple[MCPConnectionRequestModel, str]:
        await validate_authorization_client(self.settings.mcp, client_id, redirect_uri)
        self.auth.validate_resource(resource)
        if not PKCE_CHALLENGE.fullmatch(challenge) or not 16 <= len(state) <= 512:
            raise MCPAuthError("invalid_request")
        try:
            capabilities = validate_capabilities(scopes)
        except ValueError as exc:
            raise MCPAuthError("invalid_scope") from exc
        if not capabilities or set(capabilities) - set(self.settings.mcp.effective_capabilities):
            raise MCPAuthError("invalid_scope")
        # One existing singleton row serializes all workers' quotas and emergency
        # disable. No process-local or proxy-supplied identity is trusted here.
        enabled = await self.session.scalar(
            select(MCPControlModel.enabled).where(MCPControlModel.id == 1).with_for_update()
        )
        if not self.settings.mcp.enabled or enabled is not True:
            raise MCPAuthError("temporarily_unavailable", 503)
        now = datetime.now(UTC)
        if resume:
            candidates = (
                await self.session.scalars(
                    select(MCPConnectionRequestModel)
                    .where(
                        MCPConnectionRequestModel.id.in_(list(resume)),
                        MCPConnectionRequestModel.expires_at > now,
                        MCPConnectionRequestModel.status.in_(["pending", "approved", "rejected"]),
                    )
                    .with_for_update()
                )
            ).all()
            for row in candidates:
                secret = resume[row.id]
                if hmac.compare_digest(row.credential_hash, self.auth.digest(secret)) and (
                    row.client_id,
                    row.redirect_uri,
                    row.resource,
                    row.oauth_state,
                    row.code_challenge,
                    row.requested_capabilities,
                ) == (client_id, redirect_uri, resource, state, challenge, capabilities):
                    return row, secret
        cutoff = now - REQUEST_TTL
        source_hash = self.auth.digest("request-source:" + source)
        recent = MCPConnectionRequestModel.created_at > cutoff
        total = await self.session.scalar(
            select(func.count()).select_from(MCPConnectionRequestModel).where(recent)
        )
        source_total = await self.session.scalar(
            select(func.count())
            .select_from(MCPConnectionRequestModel)
            .where(recent, MCPConnectionRequestModel.source_hash == source_hash)
        )
        active = await self.session.scalar(
            select(func.count())
            .select_from(MCPConnectionRequestModel)
            .where(
                MCPConnectionRequestModel.expires_at > now,
                MCPConnectionRequestModel.status.in_(["pending", "approved"]),
            )
        )
        if (
            total >= GLOBAL_CREATION_LIMIT
            or source_total >= SOURCE_CREATION_LIMIT
            or active >= ACTIVE_REQUEST_LIMIT
        ):
            raise MCPAuthError("slow_down", 429)
        secret = new_credential("request")
        characters = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        comparison = "".join(secrets.choice(characters) for _ in range(8))
        row = MCPConnectionRequestModel(
            id=uuid.uuid4(),
            credential_hash=self.auth.digest(secret),
            source_hash=source_hash,
            comparison_code=comparison[:4] + "-" + comparison[4:],
            client_id=client_id,
            redirect_uri=redirect_uri,
            resource=resource,
            oauth_state=state,
            code_challenge=challenge,
            requested_capabilities=capabilities,
            name=DIRECT_CLIENT_NAMES.get(client_id, "MCP") + " device",
            device_platform=platform,
            status="pending",
            created_at=now,
            expires_at=now + REQUEST_TTL,
        )
        self.session.add(row)
        await AuditLogRepository(self.session).record(
            action="mcp.request_created",
            entity_type="mcp_connection_request",
            entity_id=str(row.id),
        )
        await self.session.flush()
        return row, secret

    async def requester(
        self, identifier: uuid.UUID, secret: str, *, lock: bool = False
    ) -> MCPConnectionRequestModel:
        if not secret.startswith("gcmcp_request_") or len(secret) > 128:
            raise MCPAuthError("request_unavailable", 404)
        query = (
            select(MCPConnectionRequestModel)
            .where(MCPConnectionRequestModel.id == identifier)
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        row = await self.session.scalar(query)
        if row is None or not hmac.compare_digest(row.credential_hash, self.auth.digest(secret)):
            raise MCPAuthError("request_unavailable", 404)
        return row

    @staticmethod
    def pending(row: MCPConnectionRequestModel) -> None:
        if utc(row.expires_at) <= datetime.now(UTC):
            raise MCPAuthError("request_expired", 410)
        if row.status != "pending":
            raise MCPAuthError("request_already_decided", 409)

    async def update_labels(
        self, row: MCPConnectionRequestModel, *, name: str, platform: str
    ) -> None:
        self.pending(row)
        row.name, row.device_platform = name, platform
        await self.session.flush()

    async def decide(
        self,
        identifier: uuid.UUID,
        *,
        approved: bool,
        user_id: uuid.UUID,
        security_version: int,
        mfa_at: datetime,
        name: str | None = None,
        platform: str | None = None,
        capabilities: list[str] | None = None,
        read_enabled: bool = True,
        write_enabled: bool = False,
        allowed_read_sections: list[str] | None = None,
        allowed_write_sections: list[str] | None = None,
    ) -> MCPConnectionRequestModel:
        if approved:
            await self.auth.require_enabled(lock=True)
        await self.auth.require_identity(user_id, security_version, lock=True)
        now = datetime.now(UTC)
        if not -60 <= (now - utc(mfa_at)).total_seconds() <= 600:
            raise MCPAuthError("access_denied", 403)
        row = await self.session.scalar(
            select(MCPConnectionRequestModel)
            .where(MCPConnectionRequestModel.id == identifier)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise MCPAuthError("request_unavailable", 404)
        self.pending(row)
        if approved:
            selected = validate_capabilities(
                capabilities if capabilities is not None else row.requested_capabilities
            )
            if (
                not selected
                or set(selected) - set(row.requested_capabilities)
                or set(selected) - set(self.settings.mcp.effective_capabilities)
            ):
                raise MCPAuthError("invalid_scope", 400)
            await validate_authorization_client(self.settings.mcp, row.client_id, row.redirect_uri)
            self.auth.validate_resource(row.resource)
            row.approved_capabilities = selected
            validate_device_permissions(self.settings, selected, read_enabled=read_enabled,
                write_enabled=write_enabled, allowed_read_sections=allowed_read_sections,
                allowed_write_sections=allowed_write_sections or [])
            row.read_enabled, row.write_enabled = read_enabled, write_enabled
            row.allowed_read_sections, row.allowed_write_sections = allowed_read_sections, allowed_write_sections or []
            if name is not None:
                row.name = name
            if platform is not None:
                row.device_platform = platform
        row.status = "approved" if approved else "rejected"
        row.decision_user_id, row.security_version, row.mfa_at, row.decided_at = (
            user_id,
            security_version,
            mfa_at,
            now,
        )
        await AuditLogRepository(self.session).record(
            action="mcp.request_approved" if approved else "mcp.request_rejected",
            entity_type="mcp_connection_request",
            entity_id=str(row.id),
            user_id=user_id,
        )
        await self.session.flush()
        return row

    async def finalize(self, identifier: uuid.UUID, secret: str) -> dict[str, str]:
        # Keep lock ordering aligned with emergency disable and administrator
        # decisions. The requester row is the common one-shot serialization point.
        await self.auth.require_enabled(lock=True)
        observed = await self.requester(identifier, secret)
        decision = (
            observed.status,
            observed.decision_user_id,
            observed.security_version,
            observed.mfa_at,
            tuple(observed.approved_capabilities or []),
        )
        if observed.status == "approved":
            if observed.decision_user_id is None or observed.security_version is None:
                raise MCPAuthError("access_denied", 403)
            await self.auth.require_identity(
                observed.decision_user_id, observed.security_version, lock=True
            )
        row = await self.requester(identifier, secret, lock=True)
        if (
            row.status,
            row.decision_user_id,
            row.security_version,
            row.mfa_at,
            tuple(row.approved_capabilities or []),
        ) != decision:
            raise MCPAuthError("request_decision_changed", 409)
        if utc(row.expires_at) <= datetime.now(UTC):
            raise MCPAuthError("request_expired", 410)
        if row.status not in {"approved", "rejected"}:
            raise MCPAuthError(
                "request_not_ready" if row.status == "pending" else "request_finalized", 409
            )
        await validate_authorization_client(self.settings.mcp, row.client_id, row.redirect_uri)
        self.auth.validate_resource(row.resource)
        parameters = {"state": row.oauth_state, "iss": self.settings.mcp.public_origin}
        if row.status == "approved":
            if (
                row.decision_user_id is None
                or row.security_version is None
                or row.mfa_at is None
                or row.approved_capabilities is None
            ):
                raise MCPAuthError("access_denied", 403)
            parameters["code"] = await self.auth.authorize(
                user_id=row.decision_user_id,
                security_version=row.security_version,
                mfa_at=row.mfa_at,
                client_id=row.client_id,
                redirect_uri=row.redirect_uri,
                resource=row.resource,
                challenge=row.code_challenge,
                scopes=row.approved_capabilities,
                name=row.name,
                device_platform=row.device_platform,
                read_enabled=row.read_enabled,
                write_enabled=row.write_enabled,
                allowed_read_sections=row.allowed_read_sections,
                allowed_write_sections=row.allowed_write_sections,
            )
            row.grant_id = await self.session.scalar(
                select(MCPAuthorizationCodeModel.grant_id).where(
                    MCPAuthorizationCodeModel.code_hash == self.auth.digest(parameters["code"])
                )
            )
        else:
            parameters["error"] = "access_denied"
        row.status, row.finalized_at = "finalized", datetime.now(UTC)
        await AuditLogRepository(self.session).record(
            action="mcp.request_finalized",
            entity_type="mcp_connection_request",
            entity_id=str(row.id),
            user_id=row.decision_user_id,
            metadata={"approved": "code" in parameters},
        )
        await self.session.flush()
        return {
            "redirect_url": row.redirect_uri
            + ("&" if "?" in row.redirect_uri else "?")
            + urlencode(parameters),
            "client_id": row.client_id,
            "redirect_uri": row.redirect_uri,
            "resource": row.resource,
            "state": row.oauth_state,
        }
