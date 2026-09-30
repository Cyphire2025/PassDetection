"""Code-owned, non-sensitive corrections for rejected contact workbooks."""

import json
from typing import Literal

import httpx2

from .config import ConnectorError

ContactWorkbookErrorCode = Literal[
    "contact_workbook_formulas_unsupported",
    "contact_workbook_active_content_unsupported",
    "contact_workbook_invalid_package",
    "contact_workbook_capacity_exceeded",
]

CONTACT_WORKBOOK_GUIDANCE: dict[ContactWorkbookErrorCode, str] = {
    "contact_workbook_formulas_unsupported": (
        "Create a separate values-only .xlsx copy of the contact workbook. Remove formulas "
        "and defined names, then select and upload that copy. Keep the original file."
    ),
    "contact_workbook_active_content_unsupported": (
        "Create a separate plain .xlsx copy containing only contact values. Remove macros, "
        "external links, embedded objects and active content, then select and upload that copy. "
        "Keep the original file."
    ),
    "contact_workbook_invalid_package": (
        "The file could not be read as an .xlsx workbook. Open it in your spreadsheet app and "
        "save a new plain .xlsx copy, then select and upload that copy. Keep the original file."
    ),
    "contact_workbook_capacity_exceeded": (
        "Create a smaller values-only .xlsx copy with at most 50 sheets, 2,000 total rows, "
        "64 columns per row, 50,000 total cells and 1,024 characters per cell. Keep its text "
        "and worksheet snapshot within 2 MiB and the file within 5 MiB; remove unused sheets "
        "and formatting from the copy. Select and upload the smaller copy. Keep the original file."
    ),
}


class ContactWorkbookError(ConnectorError):
    """Locally constructed correction; never reflect the server's free-form detail."""

    def __init__(self, code: ContactWorkbookErrorCode):
        self.code = code
        self.status = 422
        super().__init__(
            f"{code}: {CONTACT_WORKBOOK_GUIDANCE[code]} No business action was retried."
        )


async def workbook_response_error(response: httpx2.Response) -> ContactWorkbookError | None:
    """Bound the rejection body and accept only known codes, never remote instructions."""
    if (
        response.headers.get("content-encoding", "identity") != "identity"
        or response.headers.get("content-type", "").split(";", 1)[0] != "application/json"
    ):
        return None
    body = bytearray()
    async for part in response.aiter_bytes():
        if len(body) + len(part) > 4096:
            return None
        body.extend(part)
    try:
        raw = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        return None
    if not isinstance(raw, dict) or set(raw) != {"code", "detail"}:
        return None
    code = raw["code"]
    if not isinstance(code, str) or not isinstance(raw["detail"], str):
        return None
    for allowed in CONTACT_WORKBOOK_GUIDANCE:
        if code == allowed:
            return ContactWorkbookError(allowed)
    return None
