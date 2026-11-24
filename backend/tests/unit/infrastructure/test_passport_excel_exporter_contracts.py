"""Published exporter extension hooks retain their actual workbook behavior."""

from __future__ import annotations

import uuid
from types import MethodType

import pytest

from app.infrastructure.export import passport_excel_exporter
from app.infrastructure.export.passport_excel_exporter import PassportExcelExporter
from tests.unit.infrastructure.test_passport_excel_exporter import (
    _row_values,
    _submission,
    _worksheet,
)


def test_subclass_row_catalog_and_pending_hooks_keep_the_subclass_bound():
    calls = []

    class Customized(PassportExcelExporter):
        @staticmethod
        def _enabled_traveller_columns(*args, **kwargs):
            calls.append("columns")
            return PassportExcelExporter._enabled_traveller_columns(*args, **kwargs)

        @staticmethod
        def _custom_fields(*args, **kwargs):
            calls.append("fields")
            return [{"key": "custom:hook", "label": "Custom Answer"}]

        @classmethod
        def _submission_values(cls, *args, **kwargs):
            assert cls is Customized
            calls.append("values")
            return super()._submission_values(*args, **kwargs)

        @classmethod
        def _zone_name(cls, *args):
            assert cls is Customized
            calls.append("zone")
            return "Hook Zone"

        @staticmethod
        def _ecr_value(*args):
            calls.append("ecr")
            return "NA"

        @staticmethod
        def _group_value(*args):
            calls.append("group")
            return PassportExcelExporter._group_value(*args)

        @classmethod
        def _submission_sort_key(cls, *args, **kwargs):
            assert cls is Customized
            calls.append("submission-sort")
            return super()._submission_sort_key(*args, **kwargs)

        @classmethod
        def _pending_row_sort_key(cls, *args, **kwargs):
            assert cls is Customized
            calls.append("pending-sort")
            return super()._pending_row_sort_key(*args, **kwargs)

        @classmethod
        def _append_pending_rows(cls, *args, **kwargs):
            assert cls is Customized
            calls.append("pending")
            return super()._append_pending_rows(*args, **kwargs)

    group_id = uuid.uuid4()
    source = _submission(group_id)
    sheet = _worksheet(
        Customized().export_group(
            [source],
            group_name="Synthetic",
            group_details={group_id: {"passport_ecr_enabled": True}},
            additional_fields=[{"key": "zone_name", "label": "Zone"}],
            pending_rows=[{"GIVEN NAME": "Pending"}],
        )
    )
    headers, values = _row_values(sheet)
    assert values["Zone"] == "Hook Zone" and values["ECR"] == "NA"
    assert "Custom Answer" in headers
    assert sheet.cell(6, headers.index("GIVEN NAME") + 1).value == "Pending"
    assert set(calls) == {
        "columns",
        "fields",
        "values",
        "zone",
        "ecr",
        "group",
        "submission-sort",
        "pending-sort",
        "pending",
    }


def test_instance_projection_override_is_called_from_the_public_exporter():
    group_id = uuid.uuid4()
    source = _submission(group_id)
    exporter = PassportExcelExporter()
    called = []

    def project(self, *args, **kwargs):
        assert self is exporter
        called.append(True)
        values = PassportExcelExporter._submission_values(*args, **kwargs)
        values["GIVEN NAME"] = "Instance projection"
        return values

    exporter._submission_values = MethodType(project, exporter)
    _, values = _row_values(_worksheet(exporter.export_group([source], group_name="Synthetic")))
    assert called == [True] and values["GIVEN NAME"] == "Instance projection"


def test_repeated_custom_labels_keep_stable_columns_after_reserved_trip_fields():
    group_id = uuid.uuid4()
    source = _submission(group_id)
    source.custom_answers = [
        {"question_id": "first", "label": "Group", "value": "One"},
        {"question_id": "second", "label": "Group", "value": "Two"},
    ]
    headers, values = _row_values(
        _worksheet(
            PassportExcelExporter().export_group(
                [source],
                group_name="Synthetic",
            )
        )
    )
    assert headers[-2:] == ["Group (Custom Question)", "Group (Custom Question 2)"]
    assert values[headers[-2]] == "One" and values[headers[-1]] == "Two"


@pytest.mark.parametrize(
    ("formatter", "source", "expected"),
    [
        ("_country_display_name", None, None),
        ("_country_display_name", "   ", None),
        ("_country_display_name", " Saved Country ", "Saved Country"),
        ("_nationality_display_value", "   ", None),
        ("_nationality_display_value", "FR", "France"),
        ("_whatsapp_phone_value", "'+91-9876543210", "9876543210"),
    ],
)
def test_legacy_country_and_quoted_phone_display_preserves_supported_values(
    formatter, source, expected
):
    assert getattr(passport_excel_exporter, formatter)(source) == expected
