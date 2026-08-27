"""Sanitized domain failures for the My Photos boundary."""

from __future__ import annotations

from app.domain.exceptions.exceptions import (
    DependencyUnavailableError,
    PassDetectionError,
    RateLimitExceededError,
    ValidationError,
)


class MyPhotosError(PassDetectionError):
    """Stable, passenger-safe My Photos failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message, code=code)


class MyPhotosConflict(ValidationError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MyPhotosUnavailable(DependencyUnavailableError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MyPhotosRateLimited(RateLimitExceededError):
    def __init__(
        self,
        retry_after_seconds: int,
        message: str = "Too many Face Scan attempts. Try again later.",
        *,
        code: str = "MY_PHOTOS_COOLDOWN",
    ) -> None:
        super().__init__()
        self.message = message
        self.code = code
        # Kept numeric and tightly bounded so the presentation layer can emit a
        # standards-compliant Retry-After header without reflecting provider data.
        self.retry_after_seconds = max(1, min(retry_after_seconds, 86_400))


class MyPhotosInvalidCursor(ValidationError):
    def __init__(self, *, stale: bool = False) -> None:
        super().__init__(
            "The gallery changed. Refresh My Photos to continue."
            if stale
            else "Invalid gallery cursor."
        )
        self.code = "MY_PHOTOS_CURSOR_STALE" if stale else "MY_PHOTOS_CURSOR_INVALID"
