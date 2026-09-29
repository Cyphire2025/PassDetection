"""Canonical selectable Excel fields/defaults, without preparing a workbook."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.entities.entities import ClientGroup, PassportSubmission


class ExcelFieldOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=180)
    label: str = Field(min_length=1, max_length=120)
    source: Literal["whatsapp"]
    selected_by_default: bool = False


class ExcelGroupingOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=180)
    label: str = Field(min_length=1, max_length=120)
    fixed: bool = False


class ExcelOptionsProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: list[ExcelFieldOption]
    grouping_fields: list[ExcelGroupingOption]
    default_selected_fields: list[str]
    default_group_by_field: str | None
    agency_match_enabled: bool
    agency_match_fields: list[ExcelFieldOption]


@dataclass(frozen=True)
class ExcelOptionsSupport:
    """Fixed canonical website builders, never supplied by request arguments."""

    group_catalog: Callable[..., Any]
    combined_catalog: Callable[..., Any]
    agency_match_catalog: Callable[..., Any]
    airport_enabled: Callable[..., bool]


def project_excel_export_options(
    *,
    groups: list[ClientGroup],
    submissions: list[PassportSubmission],
    rows_by_group: dict[uuid.UUID, Any],
    selection: Literal["group", "selected_groups"],
    support: ExcelOptionsSupport,
) -> ExcelOptionsProjection:
    if not groups or (selection == "group" and len(groups) != 1):
        raise ValueError("Export options require an explicit coherent group selection")
    group = groups[0]
    catalog = (
        support.group_catalog(group, rows_by_group.get(group.id, []), submissions)
        if selection == "group"
        else support.combined_catalog(groups, rows_by_group, submissions)
    )
    fields = [ExcelFieldOption.model_validate(field) for field in catalog]
    defaults = [field.key for field in fields if field.selected_by_default]
    agency_enabled = selection == "group" and group.agency_dealership_name_enabled
    agency_fields = (
        support.agency_match_catalog(group, rows_by_group.get(group.id, []))
        if agency_enabled else []
    )
    return ExcelOptionsProjection(
        fields=fields,
        grouping_fields=[
            *([ExcelGroupingOption(key="international_airport", label="International Airport",
                                   fixed=True)]
              if any(support.airport_enabled(item) for item in groups) else []),
            *[ExcelGroupingOption(key=field.key, label=field.label) for field in fields],
        ],
        default_selected_fields=defaults,
        default_group_by_field="zone_name" if "zone_name" in defaults else None,
        agency_match_enabled=agency_enabled,
        agency_match_fields=[ExcelFieldOption.model_validate(field) for field in agency_fields],
    )
