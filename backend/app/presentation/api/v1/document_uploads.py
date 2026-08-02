"""Shared resource limits for authenticated bulk travel-document uploads."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, UploadFile, status

from app.core.config.settings import get_settings

# Keep every physical multipart request comfortably below Starlette's parser
# limit and the 120-second production worker envelope.  The browser presents
# one logical selection of up to 1,500 files and sends these bounded requests
# sequentially through the resumable upload protocol.
MAX_DOCUMENT_FILES_PER_REQUEST = 50
MAX_DOCUMENT_BATCH_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class BoundedDocumentUpload:
    filename: str
    content: bytes
    content_type: str


async def read_bounded_document_uploads(
    files: list[UploadFile],
) -> list[BoundedDocumentUpload]:
    """Read a bounded batch without trusting multipart metadata alone."""
    try:
        if not files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Upload at least one PDF",
            )
        if len(files) > MAX_DOCUMENT_FILES_PER_REQUEST:
            raise HTTPException(
                status_code=413,
                detail=f"Upload at most {MAX_DOCUMENT_FILES_PER_REQUEST} PDFs at a time",
            )

        per_file_limit = get_settings().upload_max_file_size_bytes
        declared_total = sum(
            size for file in files if isinstance((size := file.size), int) and size > 0
        )
        if any(isinstance(file.size, int) and file.size > per_file_limit for file in files):
            raise HTTPException(
                status_code=413,
                detail=f"Each PDF must be {per_file_limit // (1024 * 1024)} MB or smaller",
            )
        if declared_total > MAX_DOCUMENT_BATCH_BYTES:
            raise HTTPException(
                status_code=413,
                detail="The combined PDF upload is too large",
            )

        uploads: list[BoundedDocumentUpload] = []
        actual_total = 0
        for file in files:
            try:
                content = await file.read(per_file_limit + 1)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to read one of the uploaded PDFs",
                ) from exc
            if not content:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{bounded_upload_filename(file.filename)} is empty",
                )
            if len(content) > per_file_limit:
                raise HTTPException(
                    status_code=413,
                    detail=f"Each PDF must be {per_file_limit // (1024 * 1024)} MB or smaller",
                )
            actual_total += len(content)
            if actual_total > MAX_DOCUMENT_BATCH_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="The combined PDF upload is too large",
                )
            uploads.append(
                BoundedDocumentUpload(
                    filename=bounded_upload_filename(file.filename),
                    content=content,
                    content_type="application/pdf",
                )
            )
        return uploads
    finally:
        # FastAPI eventually closes multipart handles, but deterministic cleanup
        # matters for large batches and for validation/read failures mid-loop.
        for file in files:
            try:
                await file.close()
            except Exception:
                # A close failure must not mask the original validation or read
                # exception; the framework still owns final request teardown.
                pass


def bounded_upload_filename(value: str | None) -> str:
    """Return a database-safe basename without interpreting client paths."""

    basename = (value or "document.pdf").replace("\\", "/").rsplit("/", 1)[-1]
    normalized = " ".join(basename.replace("\x00", "").split())
    return normalized[:255] or "document.pdf"
