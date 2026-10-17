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
from starlette.exceptions import HTTPException

from app.application.mobile.notification_errors import NotificationWorkflowError
from app.application.travellers.errors import ReuseError, ReuseReason
from app.domain.services.traveller_verification import VerificationFailure
from app.infrastructure.security.traveller_reuse_crypto import ReuseCryptoUnavailable
from app.infrastructure.security.mobile_otp_rate_limiter import OTPRateLimitExceeded, OTPRateLimitUnavailable
from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ClientGroupUsedError,
    ConflictError,
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
from app.domain.exceptions.resource_capacity import ImageProcessingBusy
from app.presentation.middleware.error_response import (
    HTTP_ERROR_CODES,
)
from app.presentation.middleware.error_response import (
    error_response as _error_response,
)

logger = get_logger(__name__)

def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI application."""

    @app.exception_handler(ReuseError)
    async def returning_failure(request: Request, exc: ReuseError) -> JSONResponse:
        statuses = {ReuseReason.UNAVAILABLE: 403, ReuseReason.EXPIRED: 410,
            ReuseReason.VERIFICATION_FAILED: 403, ReuseReason.RATE_LIMITED: 429,
            ReuseReason.REVISION_CONFLICT: 409, ReuseReason.INSUFFICIENT_EVIDENCE: 403,
            ReuseReason.INFRASTRUCTURE: 503}
        messages = {ReuseReason.EXPIRED: "Your secure session expired. Start again or submit fresh documents.",
            ReuseReason.RATE_LIMITED: "Please wait before trying again. Fresh submission remains available.",
            ReuseReason.REVISION_CONFLICT: "This information changed. Refresh and verify again.",
            ReuseReason.INFRASTRUCTURE: "Verification is temporarily unavailable. Please retry shortly."}
        message = messages.get(exc.reason, "We could not verify these details. Check your information or submit fresh documents.")
        headers = {"Cache-Control": "private, no-store"}
        if exc.retry_after is not None:
            headers["Retry-After"] = str(exc.retry_after)
        return _error_response(exc.reason.value, message, statuses[exc.reason], headers=headers,
            detail={"code": exc.reason.value, "message": message, "retry_after": exc.retry_after})

    @app.exception_handler(VerificationFailure)
    async def returning_invalid(request: Request, exc: VerificationFailure) -> JSONResponse:
        return await returning_failure(request, ReuseError(ReuseReason.VERIFICATION_FAILED))

    @app.exception_handler(ReuseCryptoUnavailable)
    async def returning_crypto_unavailable(request: Request, exc: ReuseCryptoUnavailable) -> JSONResponse:
        return await returning_failure(request, ReuseError(ReuseReason.INFRASTRUCTURE))

    @app.exception_handler(OTPRateLimitExceeded)
    async def returning_rate_limited(request: Request, exc: OTPRateLimitExceeded) -> JSONResponse:
        return await returning_failure(request, ReuseError(ReuseReason.RATE_LIMITED))

    @app.exception_handler(OTPRateLimitUnavailable)
    async def returning_limit_unavailable(request: Request, exc: OTPRateLimitUnavailable) -> JSONResponse:
        return await returning_failure(request, ReuseError(ReuseReason.INFRASTRUCTURE))

    @app.exception_handler(ImageProcessingBusy)
    async def image_capacity_handler(request: Request, exc: ImageProcessingBusy) -> JSONResponse:
        return _error_response(exc.code, exc.message, status.HTTP_503_SERVICE_UNAVAILABLE,
                               headers={"Retry-After": str(exc.retry_after_seconds)})

    @app.exception_handler(NotificationWorkflowError)
    async def notification_workflow_handler(
        request: Request, exc: NotificationWorkflowError,
    ) -> JSONResponse:
        return _error_response(exc.code, exc.message,
                               {"missing": 404, "invalid": 422, "conflict": 409}[exc.category],
                               detail=exc.message)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        details = exc.detail if isinstance(exc.detail, dict) else None
        code = HTTP_ERROR_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        message = exc.detail if isinstance(exc.detail, str) else "Request could not be completed"
        if details is not None:
            if isinstance(details.get("code"), str):
                code = details["code"]
            if isinstance(details.get("message"), str):
                message = details["message"]
        return _error_response(code, message, exc.status_code, detail=exc.detail,
                               details=details, headers=exc.headers)

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

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
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
        return _error_response(
            "REQUEST_VALIDATION_ERROR", "Request validation failed",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            details=[
                        {
                            "type": error.get("type"),
                            "loc": error.get("loc"),
                            "msg": error.get("msg"),
                        }
                        for error in exc.errors()
                    ],
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.error("unhandled_exception", error_type=type(exc).__name__, request_id=request_id)
        return _error_response(
            "INTERNAL_SERVER_ERROR",
            "An unexpected error occurred. Please try again.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            headers={"X-Request-ID": request_id} if request_id else None,
        )
