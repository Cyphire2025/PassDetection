"""
Passport Field Validator
========================
Applies deterministic validation rules to extracted passport fields.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from app.application.interfaces.passport_field_validator import (
    FieldValidationIssue,
    IPassportFieldValidator,
    PassportFieldValidationResult,
)


class PassportFieldValidator(IPassportFieldValidator):
    """Rule-based validation for passport extraction output."""

    REQUIRED_FIELDS = (
        "surname",
        "given_names",
        "passport_number",
        "nationality",
        "date_of_birth",
        "date_of_expiry",
        "sex",
    )

    def validate(
        self,
        fields: dict[str, str],
        *,
        mrz_warnings: list[str] | None = None,
    ) -> PassportFieldValidationResult:
        issues: list[FieldValidationIssue] = []

        for field in self.REQUIRED_FIELDS:
            if not fields.get(field):
                issues.append(FieldValidationIssue(field=field, message="Required field was not extracted."))

        self._validate_country(fields, "nationality", issues)
        self._validate_country(fields, "issuing_country", issues)
        self._validate_passport_number(fields, issues)
        self._validate_date(fields, "date_of_birth", issues, must_be_past=True)
        self._validate_date(fields, "date_of_expiry", issues, must_be_future=True)
        self._validate_sex(fields, issues)

        for warning in mrz_warnings or []:
            issues.append(FieldValidationIssue(field="given_names", message=warning))

        status = "valid" if not issues else "review_required"
        return PassportFieldValidationResult(status=status, issues=issues)

    def _validate_country(self, fields: dict[str, str], field: str, issues: list[FieldValidationIssue]) -> None:
        value = fields.get(field)
        if value and not re.fullmatch(r"[A-Z]{3}", value):
            issues.append(FieldValidationIssue(field=field, message="Country code must be a 3-letter MRZ code."))

    def _validate_passport_number(self, fields: dict[str, str], issues: list[FieldValidationIssue]) -> None:
        value = fields.get("passport_number")
        if value and not re.fullmatch(r"[A-Z0-9<]{5,12}", value):
            issues.append(FieldValidationIssue(field="passport_number", message="Passport number has an unexpected format."))

    def _validate_date(
        self,
        fields: dict[str, str],
        field: str,
        issues: list[FieldValidationIssue],
        *,
        must_be_past: bool = False,
        must_be_future: bool = False,
    ) -> None:
        value = fields.get(field)
        if not value:
            return

        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            issues.append(FieldValidationIssue(field=field, message="Date must use YYYY-MM-DD format."))
            return

        today = date.today()
        if must_be_past and parsed >= today:
            issues.append(FieldValidationIssue(field=field, message="Date of birth must be in the past."))
        if must_be_future and parsed <= today:
            issues.append(FieldValidationIssue(field=field, message="Passport expiry must be in the future."))

    def _validate_sex(self, fields: dict[str, str], issues: list[FieldValidationIssue]) -> None:
        value = fields.get("sex")
        if value and value not in {"M", "F", "X", "<"}:
            issues.append(FieldValidationIssue(field="sex", message="Sex must be M, F, X, or blank MRZ filler."))
