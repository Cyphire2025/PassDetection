"""
Global Exception Handlers
==========================
Translates domain exceptions into structured HTTP responses.

Rules:
  - All responses use the same error envelope schema.
  - Domain exceptions map to specific HTTP status codes.
  - Internal errors are logged but NOT exposed to clients.
  - Error codes are machine-readable for the frontend.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ClientGroupUsedError,
    DependencyUnavailableError,
    DuplicateEntityError,
    EntityNotFoundError,
    GroupClosedError,
    ImageValidationError,
    LowConfidenceError,
    MRZParsingError,
    OCREngineError,
    PassDetectionError,
    RateLimitExceededError,
    StorageError,
    TokenExpiredError,
    ValidationError,
)

logger = get_logger(__name__)


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    """Create a standardised error response envelope."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI application."""

    @app.exception_handler(TokenExpiredError)
    async def token_expired_handler(request: Request, exc: TokenExpiredError) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_401_UNAUTHORIZED)

    @app.exception_handler(AuthenticationError)
    async def authentication_handler(request: Request, exc: AuthenticationError) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_401_UNAUTHORIZED)

    @app.exception_handler(AuthorizationError)
    async def authorization_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_403_FORBIDDEN)

    @app.exception_handler(EntityNotFoundError)
    async def not_found_handler(request: Request, exc: EntityNotFoundError) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)

    @app.exception_handler(DuplicateEntityError)
    async def duplicate_handler(request: Request, exc: DuplicateEntityError) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_409_CONFLICT)

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_422_UNPROCESSABLE_CONTENT)

    @app.exception_handler(ImageValidationError)
    async def image_validation_handler(
        request: Request, exc: ImageValidationError
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_422_UNPROCESSABLE_CONTENT)

    @app.exception_handler(GroupClosedError)
    async def link_expired_handler(
        request: Request, exc: GroupClosedError
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_410_GONE)

    @app.exception_handler(ClientGroupUsedError)
    async def link_used_handler(request: Request, exc: ClientGroupUsedError) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_410_GONE)

    @app.exception_handler(RateLimitExceededError)
    async def rate_limit_handler(request: Request, exc: RateLimitExceededError) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_429_TOO_MANY_REQUESTS)

    @app.exception_handler(DependencyUnavailableError)
    async def dependency_unavailable_handler(
        request: Request, exc: DependencyUnavailableError
    ) -> JSONResponse:
        logger.error("required_dependency_unavailable", code=exc.code)
        return _error_response(exc.code, exc.message, status.HTTP_503_SERVICE_UNAVAILABLE)

    @app.exception_handler(OCREngineError)
    async def ocr_engine_handler(request: Request, exc: OCREngineError) -> JSONResponse:
        logger.error("ocr_engine_failed", engine=exc.engine, code=exc.code)
        return _error_response(exc.code, exc.message, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @app.exception_handler(StorageError)
    async def storage_handler(request: Request, exc: StorageError) -> JSONResponse:
        logger.error("storage_error", code=exc.code)
        return _error_response(exc.code, exc.message, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @app.exception_handler(MRZParsingError)
    async def mrz_handler(request: Request, exc: MRZParsingError) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_422_UNPROCESSABLE_CONTENT)

    @app.exception_handler(LowConfidenceError)
    async def low_confidence_handler(request: Request, exc: LowConfidenceError) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_422_UNPROCESSABLE_CONTENT)

    @app.exception_handler(PassDetectionError)
    async def generic_domain_handler(request: Request, exc: PassDetectionError) -> JSONResponse:
        logger.warning("unhandled_domain_error", code=exc.code)
        return _error_response(exc.code, exc.message, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @app.exception_handler(RequestValidationError)
    async def pydantic_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": {
                    "code": "REQUEST_VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": [
                        {
                            "type": error.get("type"),
                            "loc": error.get("loc"),
                            "msg": error.get("msg"),
                        }
                        for error in exc.errors()
                    ],
                }
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", error_type=type(exc).__name__)
        return _error_response(
            "INTERNAL_SERVER_ERROR",
            "An unexpected error occurred. Please try again.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
