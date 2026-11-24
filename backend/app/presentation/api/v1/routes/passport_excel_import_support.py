"""Stable aliases for the canonical pure passport Excel import owners."""

from __future__ import annotations

import unicodedata as unicodedata
from collections.abc import Callable as Callable
from collections.abc import Mapping as Mapping
from dataclasses import dataclass as dataclass
from datetime import datetime as datetime
from typing import Any as Any
from typing import TypeVar as TypeVar

from app.application.mobile.passenger_phone_authority import (
    authoritative_submission_phone as authoritative_submission_phone,
)
from app.domain.value_objects.client_collection_provenance import (
    mark_client_collection_submitted as mark_client_collection_submitted,
)
from app.domain.value_objects.client_collection_provenance import (
    strip_client_collection_provenance as strip_client_collection_provenance,
)
from app.domain.value_objects.passport_fields import (
    normalize_passport_number_identity as normalize_passport_number_identity,
)
from app.domain.value_objects.passport_fields import (
    reconcile_confirmed_with_extraction as reconcile_confirmed_with_extraction,
)
from app.domain.value_objects.phone_number import phone_numbers_equal as phone_numbers_equal
from app.infrastructure.database.models import PassportSubmissionModel as PassportSubmissionModel
from app.infrastructure.imports.passport_excel_importer import (
    ImportedPassportRow as ImportedPassportRow,
)
from app.presentation.api.v1.routes import passport_excel_identity as _identity
from app.presentation.api.v1.routes import passport_excel_merge as _merge
from app.presentation.api.v1.routes import passport_excel_rows as _rows
from app.presentation.api.v1.routes.passport_excel_merge import _FieldValue as _FieldValue

_excel_identity_key = _identity._excel_identity_key
_merge_excel_fields = _merge._merge_excel_fields
_staff_code_for_submission = _identity._staff_code_for_submission
_PassportExcelImportConflict = _identity._PassportExcelImportConflict
_PassportExcelExistingIndexes = _identity._PassportExcelExistingIndexes
_excel_scalar_text = _identity._excel_scalar_text
_canonical_excel_staff_code = _identity._canonical_excel_staff_code
_canonical_excel_passport_number = _identity._canonical_excel_passport_number
_preferred_submission_value = _identity._preferred_submission_value
_strict_passport_number_for_submission = _identity._strict_passport_number_for_submission
_strict_staff_code_for_submission = _identity._strict_staff_code_for_submission
_same_passport_submission = _identity._same_passport_submission
_build_passport_excel_existing_indexes = _identity._build_passport_excel_existing_indexes
_passport_number_for_import_row = _identity._passport_number_for_import_row
_staff_code_for_import_row = _identity._staff_code_for_import_row
_normalized_excel_mapping_items = _rows._normalized_excel_mapping_items
_passport_excel_row_fingerprint = _rows._passport_excel_row_fingerprint
_deduplicate_passport_excel_rows = _rows._deduplicate_passport_excel_rows
_resolve_existing_passport_excel_submission = _identity._resolve_existing_passport_excel_submission
_apply_passport_excel_row_to_submission = _merge._apply_passport_excel_row_to_submission
_preserve_existing_collection_contact = _merge._preserve_existing_collection_contact
