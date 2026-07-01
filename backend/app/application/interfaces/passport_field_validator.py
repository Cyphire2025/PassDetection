"""
Passport Field Validator Interface
==================================
Validation contract for extracted passport fields.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class FieldValidationIssue:
    field: str
    message: str
    severity: str = "warning"


@dataclass(frozen=True)
class PassportFieldValidationResult:
    status: str
    issues: list[FieldValidationIssue] = field(default_factory=list)


class IPassportFieldValidator(ABC):
    """Contract for validating extracted passport fields."""

    @abstractmethod
    def validate(
        self,
        fields: dict[str, str],
        *,
        mrz_warnings: list[str] | None = None,
    ) -> PassportFieldValidationResult:
        """Validate extracted fields and return review metadata."""
        ...
