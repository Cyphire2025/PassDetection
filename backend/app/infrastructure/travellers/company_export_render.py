"""Bounded rendering: streamed images, explicit text cells, fixed disk budgets."""

import asyncio
import hashlib
import io
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zipfile import ZIP_STORED, ZipFile

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell

from app.application.companies.export_source import EXCEL_HEADERS, ImageSource
from app.application.travellers.asset_policy import PRIVATE_DOCUMENT_SUFFIXES
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto
from app.infrastructure.storage.minio_repository import MinioStorageRepository

MAX_PART_BYTES = 64 * 1024 * 1024
MAX_CHUNK_BYTES = 2 * 1024 * 1024
MAX_EXCEL_PEOPLE = 100_000


@dataclass(frozen=True)
class RenderedPart:
    content: bytes
    content_type: str
    count: int
    last_id: str | None


def encode_rows(rows: list[list[str | int]], crypto: TravellerReuseCrypto) -> bytes:
    content = crypto.encrypt(json.dumps(rows, ensure_ascii=False, separators=(",", ":"))).encode()
    if len(content) > MAX_CHUNK_BYTES:
        raise ValueError("export_page_byte_limit")
    return content


async def render_image_volume(rows: list[ImageSource], storage: MinioStorageRepository) -> RenderedPart:
    buffer = io.BytesIO()
    manifest: list[dict[str, str | int]] = []
    last_id = None
    consumed = 0
    with ZipFile(buffer, "w", compression=ZIP_STORED, allowZip64=False) as archive:
        for row in rows:
            # Reserve central-directory/manifest overhead before starting an
            # object; a single retained document is already capped at 20 MiB.
            if consumed + row.size > MAX_PART_BYTES - 1024 * 1024 and manifest:
                break
            last_id = str(row.identifier)
            if row.size <= 0:
                if row.key:
                    manifest.append({"asset_id": str(row.identifier), "status": "unavailable"})
                continue
            name = f"{row.person_id}/{row.revision_id}/v{row.version}_{row.side}_{row.identifier}{PRIVATE_DOCUMENT_SUFFIXES[row.content_type]}"
            digest = hashlib.sha256()
            received = 0
            with archive.open(name, "w") as target:
                async for chunk in storage.stream_file(row.key, start=0, expected_bytes=row.size):
                    received += len(chunk)
                    if received > row.size:
                        raise ValueError("export_document_size_changed")
                    target.write(chunk)
                    digest.update(chunk)
            if received != row.size:
                raise ValueError("export_document_size_changed")
            consumed += row.size
            manifest.append({"asset_id": str(row.identifier), "traveller_id": str(row.person_id),
                "document_revision_id": str(row.revision_id), "revision_number": row.version,
                "side": row.side, "source_kind": row.source_kind, "filename": name, "byte_size": row.size, "sha256": digest.hexdigest()})
        archive.writestr("manifest.json", json.dumps({"format_version": 1, "documents": manifest}, separators=(",", ":")))
    content = buffer.getvalue()
    if len(content) > MAX_PART_BYTES:
        raise ValueError("export_volume_byte_limit")
    return RenderedPart(content, "application/zip", len(manifest), last_id)


class WorkbookAssembly:
    """O(one page) RAM and <=256 MiB temporary XML/output; no dataset list."""
    def __init__(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="company-export-")
        self.path = Path(self.directory.name) / "people.xlsx"
        self.workbook = Workbook(write_only=True)
        self.sheet = self.workbook.create_sheet("Current people")
        self.count = 0
        self.append([list(EXCEL_HEADERS)])
        self.count = 0

    def append(self, rows: list[list[str | int]]) -> None:
        self.count += len(rows)
        if self.count > MAX_EXCEL_PEOPLE:
            raise ValueError("export_people_limit")
        for row in rows:
            cells = []
            for value in row:
                cell = WriteOnlyCell(self.sheet, value=value)
                if isinstance(value, str):
                    cell.data_type = "s"  # Untrusted '=...' remains text.
                cells.append(cell)
            self.sheet.append(cells)
        writer: Any = self.sheet._writer
        if writer is not None and Path(writer.out).stat().st_size > 256 * 1024 * 1024:
            raise ValueError("export_temporary_disk_limit")

    def finish(self) -> bytes:
        self.workbook.save(self.path)
        if self.path.stat().st_size > MAX_PART_BYTES:
            raise ValueError("export_workbook_byte_limit")
        return self.path.read_bytes()

    def close(self) -> None:
        writer: Any = self.sheet._writer
        try:
            self.workbook.close()
            if writer is not None:
                writer.cleanup()
        except (FileNotFoundError, OSError):
            pass
        self.directory.cleanup()


async def read_rows(storage: MinioStorageRepository, key: str, size: int,
    crypto: TravellerReuseCrypto,
) -> list[list[str | int]]:
    if not 0 < size <= MAX_CHUNK_BYTES:
        raise ValueError("export_page_byte_limit")
    data = bytearray()
    async for chunk in storage.stream_file(key, start=0, expected_bytes=size):
        data.extend(chunk)
        if len(data) > size:
            raise ValueError("export_page_size_changed")
    if len(data) != size:
        raise ValueError("export_page_size_changed")
    rows = json.loads(crypto.decrypt(data.decode()))
    if not isinstance(rows, list) or len(rows) > 250:
        raise ValueError("export_page_shape")
    for row in rows:
        if not isinstance(row, list) or len(row) != len(EXCEL_HEADERS) or any(not isinstance(value, (str, int)) for value in row):
            raise ValueError("export_page_shape")
    await asyncio.sleep(0)
    return rows
