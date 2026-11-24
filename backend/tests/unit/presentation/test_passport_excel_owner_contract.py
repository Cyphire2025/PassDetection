"""Canonical helper aliases/types must stay shared by office and MCP imports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import get_type_hints

from app.infrastructure.database.models import PassportSubmissionModel
from app.presentation.api.v1.routes import (
    passport_excel_identity as identity,
)
from app.presentation.api.v1.routes import (
    passport_excel_import_support as facade,
)
from app.presentation.api.v1.routes import (
    passport_excel_merge as merge,
)
from app.presentation.api.v1.routes import (
    passport_excel_rows as rows,
)
from app.presentation.api.v1.routes.passport_routes import constants
from app.presentation.mcp.group_workbook_tools import GROUP_WORKBOOK_SUPPORT


def test_office_and_mcp_capture_the_same_canonical_helpers_and_conflict_type():
    for actual, expected in (
        (GROUP_WORKBOOK_SUPPORT.indexes, identity._build_passport_excel_existing_indexes),
        (GROUP_WORKBOOK_SUPPORT.resolve, identity._resolve_existing_passport_excel_submission),
        (GROUP_WORKBOOK_SUPPORT.deduplicate, rows._deduplicate_passport_excel_rows),
        (GROUP_WORKBOOK_SUPPORT.apply, merge._apply_passport_excel_row_to_submission),
        (GROUP_WORKBOOK_SUPPORT.conflict_type, identity._PassportExcelImportConflict),
    ):
        assert actual is expected
        assert getattr(facade, expected.__name__) is expected
        assert getattr(constants, expected.__name__) is expected


def test_relocated_runtime_hints_resolve_the_public_record_and_type_variable_aliases():
    assert facade._FieldValue is merge._FieldValue
    assert facade._FieldValue.__bound__ is None
    assert facade._FieldValue.__constraints__ == ()
    assert get_type_hints(facade._merge_excel_fields) == {
        "existing": Mapping[str, facade._FieldValue] | None,
        "imported": Mapping[str, facade._FieldValue],
        "return": dict[str, facade._FieldValue] | None,
    }
    assert facade._PassportExcelExistingIndexes is identity._PassportExcelExistingIndexes
    assert (
        get_type_hints(facade._build_passport_excel_existing_indexes)["return"]
        is facade._PassportExcelExistingIndexes
    )
    assert (
        get_type_hints(facade._resolve_existing_passport_excel_submission)["indexes"]
        is facade._PassportExcelExistingIndexes
    )
    assert get_type_hints(facade._PassportExcelExistingIndexes) == {
        "by_passport_number": dict[str, PassportSubmissionModel],
        "by_staff_code": dict[str, PassportSubmissionModel],
        "by_identity": dict[str, tuple[PassportSubmissionModel, ...]],
    }
