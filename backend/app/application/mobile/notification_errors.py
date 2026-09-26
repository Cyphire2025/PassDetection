"""Notification workflow failures without a dependency on the HTTP adapter."""

from typing import Literal

from app.domain.exceptions.exceptions import PassDetectionError


class NotificationWorkflowError(PassDetectionError):
    def __init__(self, category: Literal["missing", "invalid", "conflict"], message: str) -> None:
        self.category = category
        super().__init__(message, code={"missing": "NOT_FOUND", "invalid": "REQUEST_VALIDATION_ERROR",
                                       "conflict": "CONFLICT"}[category])
