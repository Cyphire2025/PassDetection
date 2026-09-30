"""Code-owned, non-sensitive corrections for rejected contact workbooks."""

from typing import Literal

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


class ContactWorkbookValidationError(ValueError):
    """Only fixed codes and guidance cross the upload or connector boundary."""

    def __init__(self, code: ContactWorkbookErrorCode):
        self.code = code
        super().__init__(CONTACT_WORKBOOK_GUIDANCE[code])

    def payload(self) -> dict[str, str]:
        return {"code": self.code, "detail": CONTACT_WORKBOOK_GUIDANCE[self.code]}
