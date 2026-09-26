"""Issue access fixtures through a real durable family after the 0109 cutover."""

import uuid
from datetime import UTC, datetime, timedelta

from app.core.security.jwt import create_access_token
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository


async def issue_dashboard_access(session, user_id, role, agency_id=None, **kwargs):
    expiry = kwargs.get("session_expires_at") or datetime.now(UTC) + timedelta(days=1)
    row = await RefreshTokenRepository(session).save(
        str(uuid.uuid4()), user_id, expiry, session_version=kwargs.get("session_version", 1),
        authentication_methods=kwargs.get("authentication_methods", ("pwd",)),
        mfa_authenticated_at=kwargs.get("mfa_authenticated_at"),
    )
    return create_access_token(user_id, role, agency_id, session_id=row.session_id, **kwargs)
