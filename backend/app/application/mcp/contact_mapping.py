"""Explicit column mapping with shared WhatsApp normalization and retained failures."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.application.dtos.whatsapp_contact_dtos import (
    WhatsAppContactRejectionCode,
    WhatsAppRecipientInput,
    WhatsAppRejectedContactInput,
)
from app.application.mcp.operations import MCPOperationError
from app.application.use_cases.whatsapp.recipient_capacity import MAX_WHATSAPP_RECIPIENTS


@dataclass(frozen=True)
class ContactMappingSupport:
    """Code-owned implementations supplied by the composition root, never tool input."""

    clean_name: Callable[[Any], str | None]
    normalize_phone: Callable[[str], str | None]
    fields: Callable[..., dict[str, str]]
    merge_keys: Callable[..., list[str]]
    merge_contacts: Callable[
        [WhatsAppRecipientInput, WhatsAppRecipientInput], WhatsAppRecipientInput
    ]
    rejection_reasons: Mapping[WhatsAppContactRejectionCode, str]


class ContactColumnMapping(BaseModel):
    """Columns and header rows are one-based; only explicitly selected sheets participate."""

    model_config = ConfigDict(extra="forbid", strict=True)
    sheet_name: str = Field(min_length=1, max_length=31)
    header_row: int = Field(ge=1, le=25)
    phone_column: int = Field(ge=1, le=64)
    name_column: int | None = Field(default=None, ge=1, le=64)
    given_name_column: int | None = Field(default=None, ge=1, le=64)
    surname_column: int | None = Field(default=None, ge=1, le=64)

    @model_validator(mode="after")
    def exact_columns(self) -> ContactColumnMapping:
        names = [self.name_column, self.given_name_column, self.surname_column]
        if self.name_column is None and self.given_name_column is None:
            raise ValueError("Select a name or given-name column")
        if self.name_column is not None and any(value is not None for value in names[1:]):
            raise ValueError("Choose either a full name or given name and surname")
        selected = [self.phone_column, *(value for value in names if value is not None)]
        if len(set(selected)) != len(selected):
            raise ValueError("Each mapped column must be distinct")
        return self


@dataclass(frozen=True)
class MappedContacts:
    contacts: list[WhatsAppRecipientInput]
    rejected: list[WhatsAppRejectedContactInput]
    field_keys: list[str]
    source_rows: int
    blank_rows: int
    excluded_sheets: list[str]

    def preview(self, support: ContactMappingSupport) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for row in self.rejected:
            counts[row.reason_code] = counts.get(row.reason_code, 0) + 1
        return {
            "accepted_count": len(self.contacts),
            "rejected_count": len(self.rejected),
            "rejected_counts": counts,
            "source_rows": self.source_rows,
            "blank_rows": self.blank_rows,
            "excluded_sheets": self.excluded_sheets,
            "available_field_keys": self.field_keys,
            "recipients": [row.model_dump(mode="json") for row in self.contacts],
            "rejected_rows": [
                {
                    **row.model_dump(mode="json"),
                    "reason": support.rejection_reasons[row.reason_code],
                }
                for row in self.rejected
            ],
            "rejected_rows_truncated": False,
        }


def map_contacts(
    snapshot: dict[str, Any],
    *,
    filename: str,
    mappings: list[ContactColumnMapping],
    support: ContactMappingSupport,
) -> MappedContacts:
    sheets = {sheet["name"]: sheet["rows"] for sheet in snapshot["sheets"]}
    selected = [mapping.sheet_name for mapping in mappings]
    if len(selected) != len(set(selected)) or set(selected) - set(sheets):
        raise MCPOperationError("invalid_contact_mapping")
    contacts: dict[str, WhatsAppRecipientInput] = {}
    rejected: list[WhatsAppRejectedContactInput] = []
    keys: list[str] = []
    source_rows = blank_rows = 0
    for mapping in mappings:
        rows = sheets[mapping.sheet_name]
        if mapping.header_row > len(rows):
            raise MCPOperationError("invalid_contact_mapping")
        header = tuple(rows[mapping.header_row - 1])
        columns = [
            mapping.phone_column,
            mapping.name_column,
            mapping.given_name_column,
            mapping.surname_column,
        ]
        if max(value for value in columns if value is not None) > len(header):
            raise MCPOperationError("invalid_contact_mapping")
        keys = support.merge_keys(keys, declared_keys=header)
        for number, values in enumerate(rows[mapping.header_row :], start=mapping.header_row + 1):
            source_rows += 1
            if not any(values):
                blank_rows += 1
                continue

            def cell(column: int | None) -> str:
                return values[column - 1] if column is not None and column <= len(values) else ""

            raw_name = (
                cell(mapping.name_column)
                if mapping.name_column
                else " ".join(
                    value
                    for value in (cell(mapping.given_name_column), cell(mapping.surname_column))
                    if value
                )
            )
            raw_phone, name = cell(mapping.phone_column), support.clean_name(raw_name)
            if name and len(name) > 100:
                raise MCPOperationError("contact_name_too_long")
            fields = support.fields(
                header_row=header,
                row_values=values,
                sheet_name=mapping.sheet_name,
                source_file_name=filename,
                row_number=number,
                source_order=source_rows,
            )
            normalized = support.normalize_phone(raw_phone) if len(raw_phone) <= 64 else None
            code: WhatsAppContactRejectionCode | None = None
            if not raw_phone:
                code = "missing_phone"
            elif normalized is None:
                code = "invalid_phone"
            elif not name:
                code = "missing_name"
            else:
                incoming = WhatsAppRecipientInput(
                    name=name, phone_number=raw_phone, imported_fields=fields
                )
                if normalized in contacts:
                    contacts[normalized] = support.merge_contacts(contacts[normalized], incoming)
                    code = "duplicate_phone"
                else:
                    contacts[normalized] = incoming
            if code is not None:
                rejected.append(
                    WhatsAppRejectedContactInput(
                        source_file_name=filename,
                        sheet_name=mapping.sheet_name,
                        row_number=number,
                        raw_name=raw_name[:256] or None,
                        raw_phone_number=raw_phone[:64] or None,
                        imported_fields=fields,
                        reason_code=code,
                    )
                )
            if len(contacts) > MAX_WHATSAPP_RECIPIENTS or len(rejected) > 500:
                raise MCPOperationError("contact_import_capacity_exceeded")
    if not contacts and not rejected:
        raise MCPOperationError("contact_import_empty")
    return MappedContacts(
        list(contacts.values()),
        rejected,
        keys,
        source_rows,
        blank_rows,
        [name for name in sheets if name not in selected],
    )
