"""
Domain Exceptions
=================
All business-rule violations are expressed as typed exceptions
defined here in the Domain layer.

Rules:
  - Exceptions live in the domain; they have zero framework imports.
  - Infrastructure and presentation layers catch these and translate
    them into HTTP responses or log entries.
  - Never raise raw Exception or ValueError from business logic.
"""

from __future__ import annotations

import uuid


class PassDetectionError(Exception):
    """Base exception for all platform errors."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


# ── Authentication & Authorization ────────────────────────────────────────────

class AuthenticationError(PassDetectionError):
    """Raised when credentials are invalid or missing."""

    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message, code="AUTHENTICATION_ERROR")


class AuthorizationError(PassDetectionError):
    """Raised when a user lacks permission to perform an action."""

    def __init__(self, message: str = "Insufficient permissions") -> None:
        super().__init__(message, code="AUTHORIZATION_ERROR")


class TokenExpiredError(AuthenticationError):
    """Raised when a JWT or refresh token has expired."""

    def __init__(self) -> None:
        super().__init__("Token has expired")
        self.code = "TOKEN_EXPIRED"


# ── Entity Not Found ──────────────────────────────────────────────────────────

class EntityNotFoundError(PassDetectionError):
    """Raised when a requested entity does not exist."""

    def __init__(self, entity: str, identifier: str | int | uuid.UUID) -> None:
        super().__init__(
            f"{entity} with identifier '{identifier}' was not found",
            code="NOT_FOUND",
        )
        self.entity = entity
        self.identifier = identifier


# ── Validation ────────────────────────────────────────────────────────────────

class ValidationError(PassDetectionError):
    """Raised when domain-level validation fails."""

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message, code="VALIDATION_ERROR")
        self.field = field


class DuplicateEntityError(PassDetectionError):
    """Raised when attempting to create an entity that already exists."""

    def __init__(self, entity: str, field: str, value: str) -> None:
        super().__init__(
            f"{entity} with {field}='{value}' already exists",
            code="DUPLICATE_ENTITY",
        )


# ── File / Image Processing ───────────────────────────────────────────────────

class ImageValidationError(PassDetectionError):
    """Raised when an uploaded image fails format or quality checks."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="IMAGE_VALIDATION_ERROR")


class StorageError(PassDetectionError):
    """Raised when object storage operations fail."""

    def __init__(self, message: str) -> None:
        super().__init__(message, code="STORAGE_ERROR")


# ── OCR & Processing ──────────────────────────────────────────────────────────

class OCREngineError(PassDetectionError):
    """Raised when an OCR engine fails to process an image."""

    def __init__(self, engine: str, reason: str) -> None:
        super().__init__(
            f"OCR engine '{engine}' failed: {reason}",
            code="OCR_ENGINE_ERROR",
        )
        self.engine = engine


class MRZParsingError(PassDetectionError):
    """Raised when MRZ lines cannot be parsed from an image."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"MRZ parsing failed: {reason}", code="MRZ_PARSING_ERROR")


class LowConfidenceError(PassDetectionError):
    """Raised when OCR confidence falls below acceptable threshold."""

    def __init__(self, confidence: float, threshold: float) -> None:
        super().__init__(
            f"OCR confidence {confidence:.2f} is below threshold {threshold:.2f}",
            code="LOW_CONFIDENCE",
        )
        self.confidence = confidence
        self.threshold = threshold


# ── Upload Links ──────────────────────────────────────────────────────────────

class GroupClosedError(PassDetectionError):
    """Raised when a client upload link has expired."""

    def __init__(self) -> None:
        super().__init__("Upload link has expired", code="CLIENT_GROUP_EXPIRED")


class ClientGroupUsedError(PassDetectionError):
    """Raised when a single-use upload link is re-used."""

    def __init__(self) -> None:
        super().__init__("Upload link has already been used", code="CLIENT_GROUP_USED")


# ── Rate Limiting ─────────────────────────────────────────────────────────────

class RateLimitExceededError(PassDetectionError):
    """Raised when a client exceeds the rate limit."""

    def __init__(self) -> None:
        super().__init__("Rate limit exceeded. Please try again later.", code="RATE_LIMIT_EXCEEDED")
