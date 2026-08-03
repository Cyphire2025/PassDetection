"""JWT and opaque refresh-token primitives for the GC mobile API.

Mobile tokens are deliberately not dashboard access tokens. The distinct token
type, issuer/audience checks, and optional dedicated key prevent a bearer token
issued to the app from being accepted by the cookie-authenticated dashboard.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from app.core.config.settings import get_settings
from app.domain.exceptions.exceptions import AuthenticationError, TokenExpiredError

MOBILE_ACCESS_TOKEN_TYPE = "mobile_access"
MOBILE_DOCUMENT_GRANT_TYPE = "mobile_document_grant"
MobilePrincipalType = Literal["passenger", "client_manager", "coordinator"]


@dataclass(frozen=True, slots=True)
class MobileAccessClaims:
    principal_id: uuid.UUID
    account_id: uuid.UUID
    principal_type: MobilePrincipalType
    agency_id: uuid.UUID
    session_id: uuid.UUID
    session_generation: int
    password_change_required: bool
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class MobileDocumentGrantClaims:
    principal_id: uuid.UUID
    principal_type: MobilePrincipalType
    agency_id: uuid.UUID
    session_id: uuid.UUID
    session_generation: int
    gc_group_access_id: uuid.UUID
    group_id: uuid.UUID
    access_generation: int
    document_id: uuid.UUID
    document_version: int
    document_scope: Literal["personal", "common"]
    passenger_identity_id: uuid.UUID | None
    expires_at: datetime


def _mobile_secret(*, purpose: str) -> bytes:
    settings = get_settings()
    configured = settings.mobile.jwt_secret_key
    if configured is not None:
        base = configured.get_secret_value().encode("utf-8")
    else:
        if settings.is_production and settings.mobile.enabled:
            raise RuntimeError(
                "MOBILE_JWT_SECRET_KEY must be configured when the mobile API is enabled in production"
            )
        base = settings.app_secret_key.encode("utf-8")
    return hmac.new(base, f"gc-mobile:{purpose}:v1".encode(), hashlib.sha256).digest()


def create_mobile_access_token(
    *,
    principal_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
    principal_type: MobilePrincipalType,
    agency_id: uuid.UUID,
    session_id: uuid.UUID,
    session_generation: int,
    password_change_required: bool = False,
) -> tuple[str, datetime]:
    settings = get_settings().mobile
    # JWT numeric dates have second precision; return the same precision to
    # clients so expiry comparisons do not disagree by microseconds.
    now = datetime.now(tz=UTC).replace(microsecond=0)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(principal_id),
        # `sub` remains the selected authorization identity. `aid` is the
        # stable account/cache namespace and does not rotate on trip switch.
        "aid": str(account_id or principal_id),
        "principal_type": principal_type,
        "agency_id": str(agency_id),
        "session_id": str(session_id),
        "session_generation": session_generation,
        "pwd_change_required": password_change_required,
        "type": MOBILE_ACCESS_TOKEN_TYPE,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": expires_at,
        "jti": str(uuid.uuid4()),
    }
    return (
        jwt.encode(payload, _mobile_secret(purpose="access"), algorithm="HS256"),
        expires_at,
    )


def decode_mobile_access_token(token: str) -> MobileAccessClaims:
    settings = get_settings().mobile
    try:
        payload = jwt.decode(
            token,
            _mobile_secret(purpose="access"),
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
        if payload.get("type") != MOBILE_ACCESS_TOKEN_TYPE:
            raise AuthenticationError("Invalid mobile token type")
        principal_type = payload.get("principal_type")
        if principal_type not in {"passenger", "client_manager", "coordinator"}:
            raise AuthenticationError("Invalid mobile principal type")
        generation = int(payload["session_generation"])
        if generation < 1:
            raise ValueError("invalid session generation")
        exp = datetime.fromtimestamp(float(payload["exp"]), tz=UTC)
        return MobileAccessClaims(
            principal_id=uuid.UUID(str(payload["sub"])),
            # Tokens issued before account namespaces were introduced remain
            # valid and retain their former principal-based namespace.
            account_id=uuid.UUID(str(payload.get("aid", payload["sub"]))),
            principal_type=principal_type,
            agency_id=uuid.UUID(str(payload["agency_id"])),
            session_id=uuid.UUID(str(payload["session_id"])),
            session_generation=generation,
            password_change_required=payload.get("pwd_change_required") is True,
            expires_at=exp,
        )
    except TokenExpiredError:
        raise
    except AuthenticationError:
        raise
    except ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except InvalidTokenError as exc:
        raise AuthenticationError("Invalid mobile access token") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthenticationError("Invalid mobile access token payload") from exc


def create_mobile_document_grant(
    *,
    claims: MobileAccessClaims,
    gc_group_access_id: uuid.UUID,
    group_id: uuid.UUID,
    access_generation: int,
    document_id: uuid.UUID,
    document_version: int,
    document_scope: Literal["personal", "common"],
    passenger_identity_id: uuid.UUID | None,
) -> tuple[str, datetime]:
    """Issue a short-lived, device-session-bound document capability.

    The capability is intentionally separate from the ordinary mobile access
    token.  A content request must present both tokens, and the content handler
    re-evaluates the live device session and group policy before serving bytes.
    """

    settings = get_settings().mobile
    if document_scope == "personal" and passenger_identity_id is None:
        raise ValueError("Personal document grants require a passenger identity")
    if document_scope == "common" and passenger_identity_id is not None:
        raise ValueError("Common document grants cannot name a passenger identity")
    if document_version < 1 or access_generation < 0:
        raise ValueError("Invalid document grant version")
    now = datetime.now(tz=UTC).replace(microsecond=0)
    expires_at = now + timedelta(seconds=settings.document_grant_ttl_seconds)
    payload: dict[str, Any] = {
        "sub": str(claims.principal_id),
        "principal_type": claims.principal_type,
        "agency_id": str(claims.agency_id),
        "session_id": str(claims.session_id),
        "session_generation": claims.session_generation,
        "gc_group_access_id": str(gc_group_access_id),
        "group_id": str(group_id),
        "access_generation": access_generation,
        "document_id": str(document_id),
        "document_version": document_version,
        "document_scope": document_scope,
        "passenger_identity_id": (
            str(passenger_identity_id) if passenger_identity_id is not None else None
        ),
        "type": MOBILE_DOCUMENT_GRANT_TYPE,
        "iss": settings.jwt_issuer,
        "aud": f"{settings.jwt_audience}:document",
        "iat": now,
        "exp": expires_at,
        "jti": str(uuid.uuid4()),
    }
    return (
        jwt.encode(payload, _mobile_secret(purpose="document"), algorithm="HS256"),
        expires_at,
    )


def decode_mobile_document_grant(token: str) -> MobileDocumentGrantClaims:
    settings = get_settings().mobile
    try:
        payload = jwt.decode(
            token,
            _mobile_secret(purpose="document"),
            algorithms=["HS256"],
            audience=f"{settings.jwt_audience}:document",
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
        if payload.get("type") != MOBILE_DOCUMENT_GRANT_TYPE:
            raise AuthenticationError("Invalid document grant type")
        principal_type = payload.get("principal_type")
        if principal_type not in {"passenger", "client_manager", "coordinator"}:
            raise AuthenticationError("Invalid document grant principal type")
        document_scope = payload.get("document_scope")
        if document_scope not in {"personal", "common"}:
            raise AuthenticationError("Invalid document grant scope")
        session_generation = int(payload["session_generation"])
        access_generation = int(payload["access_generation"])
        document_version = int(payload["document_version"])
        if session_generation < 1 or access_generation < 0 or document_version < 1:
            raise ValueError("invalid document grant generation")
        passenger_identity_raw = payload.get("passenger_identity_id")
        passenger_identity_id = (
            uuid.UUID(str(passenger_identity_raw))
            if passenger_identity_raw is not None
            else None
        )
        if (document_scope == "personal") != (passenger_identity_id is not None):
            raise ValueError("invalid document grant passenger scope")
        return MobileDocumentGrantClaims(
            principal_id=uuid.UUID(str(payload["sub"])),
            principal_type=principal_type,
            agency_id=uuid.UUID(str(payload["agency_id"])),
            session_id=uuid.UUID(str(payload["session_id"])),
            session_generation=session_generation,
            gc_group_access_id=uuid.UUID(str(payload["gc_group_access_id"])),
            group_id=uuid.UUID(str(payload["group_id"])),
            access_generation=access_generation,
            document_id=uuid.UUID(str(payload["document_id"])),
            document_version=document_version,
            document_scope=document_scope,
            passenger_identity_id=passenger_identity_id,
            expires_at=datetime.fromtimestamp(float(payload["exp"]), tz=UTC),
        )
    except TokenExpiredError:
        raise
    except AuthenticationError:
        raise
    except ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except InvalidTokenError as exc:
        raise AuthenticationError("Invalid document download grant") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthenticationError("Invalid document download grant payload") from exc


def validate_mobile_document_grant(
    grant: MobileDocumentGrantClaims,
    *,
    access_claims: MobileAccessClaims,
    gc_group_access_id: uuid.UUID,
    group_id: uuid.UUID,
    access_generation: int,
    document_id: uuid.UUID,
    document_version: int,
    document_scope: Literal["personal", "common"],
    passenger_identity_id: uuid.UUID | None,
) -> None:
    """Bind a decoded capability to the live bearer/session/resource context."""

    expected = (
        access_claims.principal_id,
        access_claims.principal_type,
        access_claims.agency_id,
        access_claims.session_id,
        access_claims.session_generation,
        gc_group_access_id,
        group_id,
        access_generation,
        document_id,
        document_version,
        document_scope,
        passenger_identity_id,
    )
    actual = (
        grant.principal_id,
        grant.principal_type,
        grant.agency_id,
        grant.session_id,
        grant.session_generation,
        grant.gc_group_access_id,
        grant.group_id,
        grant.access_generation,
        grant.document_id,
        grant.document_version,
        grant.document_scope,
        grant.passenger_identity_id,
    )
    if not hmac.compare_digest(repr(actual).encode(), repr(expected).encode()):
        raise AuthenticationError("Document download grant does not match this request")


def create_mobile_refresh_token() -> tuple[str, datetime]:
    expires_at = datetime.now(tz=UTC) + timedelta(
        days=get_settings().mobile.refresh_token_expire_days
    )
    return secrets.token_urlsafe(48), expires_at


def hash_mobile_refresh_token(token: str) -> str:
    return hmac.new(
        _mobile_secret(purpose="refresh"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def hash_mobile_lookup(value: str, *, purpose: str) -> str:
    """Return a non-reversible deterministic lookup/audit digest."""

    return hmac.new(
        _mobile_secret(purpose=f"lookup:{purpose}"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def hash_mobile_otp_code(challenge_id: uuid.UUID, code: str) -> str:
    return hash_mobile_lookup(f"{challenge_id}:{code}", purpose="otp-code")


def hash_mobile_secondary_factor(identity_id: uuid.UUID, value: str) -> str:
    normalized = " ".join(value.strip().casefold().split())
    return hash_mobile_lookup(f"{identity_id}:{normalized}", purpose="secondary-factor")
