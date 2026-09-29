"""Explicit local XLSX selection to the fixed authenticated agency import route."""

import hashlib
import hmac
import re
import uuid
from datetime import datetime

from .config import ConnectorError
from .files import provided_file_chunks

MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_BYTES = 5 * 1024 * 1024


async def upload_contact_excel(client, path, *, allowed_paths, agency_id: uuid.UUID) -> dict:
    size, digest = 0, hashlib.sha256()
    async for part in provided_file_chunks(path, allowed_paths=allowed_paths, max_bytes=MAX_BYTES):
        size += len(part)
        digest.update(part)
    if size == 0 or path.suffix.lower() != ".xlsx":
        raise ConnectorError("Select a nonempty XLSX workbook for contact import.")
    checksum = digest.hexdigest()
    raw = await client._json(
        "POST", f"{client.config.origin}/mcp/contact-imports/uploads", expected_status=201,
        params={"agency_id": str(agency_id), "filename": path.name},
        headers={"Content-Type": MEDIA_TYPE, "X-Artifact-Size": str(size), "X-Artifact-SHA256": checksum},
        content=provided_file_chunks(path, allowed_paths=allowed_paths, max_bytes=MAX_BYTES),
    )
    try:
        if (not re.fullmatch(r"gcmcp_contacts_[A-Za-z0-9_-]{64}", raw["upload_id"])
                or raw["agency_id"] != str(agency_id)
                or not isinstance(raw["filename"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", raw["filename"])
                or not raw["filename"].lower().endswith(".xlsx")
                or raw["media_type"] != MEDIA_TYPE or type(raw["byte_size"]) is not int
                or raw["byte_size"] != size or not hmac.compare_digest(raw["sha256"], checksum)
                or raw["business_import"] != "not_started"):
            raise ValueError()
        if datetime.fromisoformat(raw["expires_at"]).tzinfo is None:
            raise ValueError()
        sheets = raw["worksheets"]
        if not isinstance(sheets, list) or not 1 <= len(sheets) <= 50:
            raise ValueError()
        for sheet in sheets:
            if (not isinstance(sheet, dict) or not isinstance(sheet.get("name"), str)
                    or not 1 <= len(sheet["name"]) <= 31
                    or type(sheet.get("row_count")) is not int or not 0 <= sheet["row_count"] <= 2000
                    or type(sheet.get("column_count")) is not int or not 0 <= sheet["column_count"] <= 64):
                raise ValueError()
        # Do not reflect extra URLs, prompts, paths or fields in a server response.
        return {**{key: raw[key] for key in (
            "upload_id", "agency_id", "filename", "media_type", "byte_size", "sha256", "expires_at", "business_import",
        )}, "worksheets": [{key: sheet[key] for key in ("name", "row_count", "column_count")} for sheet in sheets]}
    except (KeyError, TypeError, ValueError):
        raise ConnectorError("The staged contact upload receipt does not match the selected workbook and agency.") from None
