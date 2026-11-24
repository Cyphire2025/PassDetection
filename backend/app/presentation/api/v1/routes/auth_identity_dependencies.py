"""Typed call-time seams retained by the public identity route facade."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import NoReturn, Protocol, TypeAlias, TypeVar

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.domain.entities.entities import User
from app.infrastructure.database.models import UserSecurityStateModel
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.security.identity_recovery_rate_limiter import IdentityRecoveryRateLimiter
from app.infrastructure.security.mfa_step_up_rate_limiter import MFAStepUpRateLimiter
from app.presentation.api.v1.schemas.auth_schemas import AuthChallengeResponse, AuthResponse

DateTimeClass: TypeAlias = type[datetime]
SettingsProvider: TypeAlias = Callable[[], Settings]
RequestHash: TypeAlias = Callable[[Request, str], str | None]
DenyVerification: TypeAlias = Callable[[AsyncSession], Awaitable[NoReturn]]
ExistingDeadline: TypeAlias = Callable[[Request], datetime | None]
StepUpLimiterFactory: TypeAlias = Callable[[], MFAStepUpRateLimiter]
RecoveryLimiterFactory: TypeAlias = Callable[[], IdentityRecoveryRateLimiter]
_Result = TypeVar("_Result")


class PasswordWork(Protocol):
    def __call__(self, operation: Callable[..., _Result], *args: str) -> Awaitable[_Result]: ...


class FactorVerifier(Protocol):
    def __call__(
        self,
        *,
        repository: IdentitySecurityRepository,
        state: UserSecurityStateModel,
        code: str,
        secret_ciphertext: str,
        now: datetime,
        allow_recovery: bool,
    ) -> Awaitable[tuple[bool, str, int | None]]: ...


class SessionIssuer(Protocol):
    def __call__(
        self,
        *,
        user: User,
        state: UserSecurityStateModel,
        request: Request,
        response: Response,
        session: AsyncSession,
        method: str,
        mfa_at: datetime | None,
        session_expires_at: datetime | None = None,
    ) -> Awaitable[AuthResponse]: ...


class BeginChallenge(Protocol):
    def __call__(
        self,
        *,
        user: User,
        request: Request,
        session: AsyncSession,
    ) -> Awaitable[AuthChallengeResponse | None]: ...
