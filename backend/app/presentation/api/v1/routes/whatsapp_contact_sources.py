"""Recover bounded original duplicate rows independently of edited delivery recipients."""

from fastapi import HTTPException, UploadFile

from app.application.use_cases.whatsapp.contact_import_limits import (
    MAX_WHATSAPP_EXCEL_ROWS,
    MAX_WHATSAPP_SOURCE_FILES,
)
from app.presentation.api.v1.routes.whatsapp_contact_import import _parse_excel_contacts_result
from app.presentation.api.v1.routes.whatsapp_contact_support import (
    _rejected_contact_fingerprint,
    _WhatsAppExcelContactParseResult,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppRejectedContactInput


def excel_rejected_contacts(
    result: _WhatsAppExcelContactParseResult,
    existing: list[WhatsAppRejectedContactInput] | None = None,
) -> list[WhatsAppRejectedContactInput]:
    """Convert every bounded source row, never the capped preview projection."""
    sources = [WhatsAppRejectedContactInput(
        source_file_name=row.imported_fields.get("source_file", "contacts.xlsx"),
        sheet_name=row.sheet_name, row_number=row.row_number,
        raw_name=row.raw_name, raw_phone_number=row.raw_phone_number,
        imported_fields=row.imported_fields, reason_code=row.reason_code,
    ) for row in result.rejected_rows]
    unique: dict[str, WhatsAppRejectedContactInput] = {}
    for row in [*sources, *(existing or [])]:
        unique.setdefault(_rejected_contact_fingerprint(row), row)
    return list(unique.values())


async def recover_excel_duplicate_sources(
    files: list[UploadFile] | None,
    existing: list[WhatsAppRejectedContactInput],
) -> list[WhatsAppRejectedContactInput]:
    """Keep UI edits authoritative while recovering omitted duplicate sources.

    Parse sequentially before row locks; O(2,000 bounded rows) retained memory.
    Source workbooks never activate or overwrite delivery recipients here.
    """
    if not files:
        return existing
    if len(files) > MAX_WHATSAPP_SOURCE_FILES:
        raise HTTPException(400, f"Submit at most {MAX_WHATSAPP_SOURCE_FILES} source workbooks")
    contacts, source_count = existing, 0
    for file in files:
        result = await _parse_excel_contacts_result(file)
        source_count += len(result.contacts) + result.rejected_count
        if source_count > MAX_WHATSAPP_EXCEL_ROWS:
            raise HTTPException(400, f"Source workbooks can contain at most {MAX_WHATSAPP_EXCEL_ROWS} contact entries in total")
        contacts = excel_rejected_contacts(result, contacts)
        if len(contacts) > MAX_WHATSAPP_EXCEL_ROWS:
            raise HTTPException(400, f"A WhatsApp list can contain at most {MAX_WHATSAPP_EXCEL_ROWS} rejected contacts")
    return contacts


