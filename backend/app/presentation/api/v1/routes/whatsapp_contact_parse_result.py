"""Parsed workbook rows and complete rejection totals."""

from __future__ import annotations

from dataclasses import dataclass

from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppContactPreviewRejectedRow,
    WhatsAppContactRejectionCode,
    WhatsAppRecipientInput,
)


@dataclass(slots=True)
class _WhatsAppExcelContactParseResult:
    __module__ = "app.presentation.api.v1.routes.whatsapp_contact_support"
    contacts: list[WhatsAppRecipientInput]
    rejected_rows: list[WhatsAppContactPreviewRejectedRow]
    rejected_counts: dict[WhatsAppContactRejectionCode, int]
    field_keys: list[str]

    @property
    def rejected_count(self) -> int:
        return sum(self.rejected_counts.values())
