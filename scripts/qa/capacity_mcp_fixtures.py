"""Test-only dedicated grants for the fixed local combined workload."""

import uuid
from datetime import UTC, datetime

from qualification_application_journey import isolated
from sqlalchemy import update

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import pkce_challenge
from app.core.config.settings import get_settings
from app.infrastructure.database.mcp_models import MCPControlModel
from app.infrastructure.database.models import UserModel, UserSecurityStateModel
from app.infrastructure.database.session import AsyncSessionFactory


async def seed_mcp(run_id: str, groups: list[dict], password_hash: str) -> list[dict]:
    isolated()
    settings = get_settings()
    if (not settings.mcp.enabled or settings.mcp.public_origin != "https://localhost:58443"
            or settings.mcp.frontend_origin != "https://localhost:58443"
            or set(settings.mcp.enabled_capabilities) != {"mcp:read", "mcp:export"}):
        raise RuntimeError("The explicit local MCP capacity overlay is required")
    actors = []
    now = datetime.now(UTC)
    async with AsyncSessionFactory() as db:
        await db.execute(update(MCPControlModel).where(MCPControlModel.id == 1).values(enabled=True))
        for index, group in enumerate(groups[:2]):
            user_id = uuid.uuid5(uuid.UUID(run_id), f"mcp-capacity-{index}")
            db.add(UserModel(id=user_id, email=f"{run_id}-mcp-{index}@example.test",
                             full_name="Synthetic MCP capacity operator", role="super_admin",
                             is_active=True, hashed_password=password_hash))
            await db.flush()
            db.add(UserSecurityStateModel(user_id=user_id, credential_state="active",
                                           session_version=1, mfa_enabled_at=now))
            await db.flush()
            auth = MCPAuthorizationService(db, settings)
            verifier = uuid.uuid4().hex + uuid.uuid4().hex
            fields = {"client_id": "global-connects-desktop", "redirect_uri": "http://127.0.0.1:8765/callback",
                      "resource": settings.mcp.resource}
            code = await auth.authorize(user_id=user_id, security_version=1, mfa_at=now,
                                        challenge=pkce_challenge(verifier), scopes=["mcp:read", "mcp:export"],
                                        name="Synthetic capacity grant", **fields)
            token = await auth.exchange_code(code=code, verifier=verifier, **fields)
            actors.append({"token": token["access_token"], "group_id": group["group_id"],
                           "agency_id": group["agency_id"], "group_size": group["group_size"],
                           "tenant": group["tenant"], "export_size": min(group["group_size"], 1500),
                           "export_submission_ids": [str(uuid.uuid5(uuid.UUID(run_id), f"passenger-{group['tenant']}-{row}"))
                                                     for row in range(1500)] if group["group_size"] > 1500 else [],
                           "cohort": "mcp_large_group" if index == 0 else "mcp_small_group"})
        await db.commit()
    return actors
