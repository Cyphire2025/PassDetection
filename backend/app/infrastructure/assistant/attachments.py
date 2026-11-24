"""Validate bounded, private assistant attachments before any parsing or model access."""

from __future__ import annotations

import asyncio
import io
import re
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from app.application.assistant.contracts import AssistantError
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.security.upload_security import (
    UploadSecurityContext,
    UploadSecurityEvidenceError,
    UploadSecurityService,
)
from app.infrastructure.security.upload_validator import (
    DocumentIngestionDisabledError,
    MalwareScannerConfigurationError,
    MalwareScannerUnavailableError,
)

ACCEPTED = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".md", ".csv", ".json", ".docx", ".xlsx"}
)
MAX_UPLOAD = 8 * 1024 * 1024


def _office_text(content: bytes, extension: str) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if (
            len(entries) > 250
            or sum(item.file_size for item in entries) > 16 * 1024 * 1024
            or any(
                item.flag_bits & 1 or item.filename.lower().endswith(("vbaproject.bin", ".exe"))
                for item in entries
            )
        ):
            raise ValueError("Office archive exceeds its safe limits")
        for entry in entries:
            if entry.filename.casefold().endswith(".xml"):
                data = archive.read(entry).replace(b"\x00", b"").upper()
                if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
                    raise ValueError("Active Office XML is unavailable")
        if extension == ".docx":
            data = archive.read("word/document.xml")
            if len(data) > 2 * 1024 * 1024 or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
                raise ValueError("Document XML is unavailable")
            root = ElementTree.fromstring(data)
            return "\n".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))[
                :60000
            ]
        # openpyxl is already a pinned backend dependency. Formula expressions are never evaluated.
        import openpyxl

        book = openpyxl.load_workbook(
            io.BytesIO(content), read_only=True, data_only=True, keep_links=False
        )
        try:
            chunks: list[str] = []
            characters = 0
            for sheet in book.worksheets[:8]:
                chunks.append(f"Sheet: {sheet.title}")
                for row in sheet.iter_rows(max_row=500, max_col=30, values_only=True):
                    line = " | ".join(
                        str(value)[:1000] if value is not None else "" for value in row
                    )
                    characters += len(line)
                    if characters > 60000:
                        return "\n".join(chunks)[:60000]
                    chunks.append(line)
            return "\n".join(chunks)[:60000]
        finally:
            book.close()


async def prepare_attachment(
    content: bytes, filename: str, content_type: str, context: UploadSecurityContext
) -> tuple[bytes, str, str, str | None]:
    name = PurePosixPath(filename.replace("\\", "/")).name
    name = "".join(character for character in name if character.isprintable())[:140] or "Attachment"
    extension = PurePosixPath(name).suffix.casefold()
    if not content or len(content) > MAX_UPLOAD:
        raise AssistantError("file_limit", "Upload a non-empty file of 8 MB or smaller.", 413)
    if extension not in ACCEPTED:
        raise AssistantError(
            "unsupported_file", "Choose a PDF, image, text, CSV, Word, or Excel file.", 415
        )
    security: UploadSecurityService | None = None
    try:
        security = UploadSecurityService()
        if extension in {".png", ".jpg", ".jpeg", ".webp"}:
            image = await security.validate_image(
                content=content,
                filename=name,
                declared_content_type=content_type,
                context=context,
                max_bytes=MAX_UPLOAD,
                max_dimension=5000,
                allowed_source_formats=frozenset({"JPEG", "PNG", "WEBP"}),
            )
            suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(
                image.content_type, extension
            )
            return image.content, PurePosixPath(name).stem + suffix, image.content_type, None
        if extension == ".pdf":
            await security.validate_document(
                content=content,
                declared_content_type="application/pdf",
                context=context,
                max_bytes=5 * 1024 * 1024,
            )
            return content, name, "application/pdf", None
        # Preserve the existing durable security decision without interpreting arbitrary bytes as a PDF.
        await security._scan_original(
            content=content, declared_media_type=content_type, context=context
        )
        if extension in {".docx", ".xlsx"}:
            text = await asyncio.to_thread(_office_text, content, extension)
        else:
            text = content.decode("utf-8-sig")
            if "\0" in text:
                raise ValueError("Text contains binary content")
            text = text[:60000]
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        text = text.encode("utf-8")[: 128 * 1024].decode("utf-8", errors="ignore")
        mime = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }.get(extension, "text/plain")
        await security._record(
            content=content,
            declared_media_type=mime,
            context=context,
            scan_status="clean",
            disposition="accepted",
        )
        return content, name, mime, text
    except (
        MalwareScannerUnavailableError,
        MalwareScannerConfigurationError,
        UploadSecurityEvidenceError,
    ):
        raise AssistantError(
            "scanner_unavailable", "File checks are temporarily unavailable. Please try again."
        ) from None
    except DocumentIngestionDisabledError:
        raise AssistantError(
            "uploads_disabled", "File uploads are not enabled on this server."
        ) from None
    except (
        ImageValidationError,
        ValueError,
        UnicodeError,
        zipfile.BadZipFile,
        KeyError,
        ElementTree.ParseError,
    ):
        if security is not None and extension not in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}:
            try:
                await security._record(
                    content=content,
                    declared_media_type=content_type,
                    context=context,
                    scan_status="malformed",
                    disposition="rejected",
                    error_code="ASSISTANT_FILE_INVALID",
                )
            except UploadSecurityEvidenceError:
                raise AssistantError(
                    "scanner_unavailable",
                    "File checks are temporarily unavailable. Please try again.",
                ) from None
        raise AssistantError(
            "file_rejected",
            "This file could not pass the upload checks. Try a readable, unencrypted file.",
            422,
        ) from None
