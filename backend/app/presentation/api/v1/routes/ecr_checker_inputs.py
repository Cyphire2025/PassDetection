"""ECR upload admission and request identity validation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import NamedTuple
from weakref import WeakKeyDictionary

from fastapi import HTTPException, UploadFile

from app.presentation.api.v1.schemas.ecr_schemas import EcrBatchResponse

_UPLOAD_GATES: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = WeakKeyDictionary()


async def _run_admitted_upload(
    operation: Callable[[], Awaitable[EcrBatchResponse]],
) -> EcrBatchResponse:
    """One decoded ECR upload per API process, including cancellation cleanup.

    Waiting requests keep their UploadFile spools without materializing the
    original chunks. A disconnected caller must not release admission while a
    decoder thread or staged storage operation is still using its memory or
    request session, so admitted work settles before cancellation propagates.
    """
    loop = asyncio.get_running_loop()
    gate = _UPLOAD_GATES.setdefault(loop, asyncio.Semaphore(1))
    async with gate:
        work = asyncio.ensure_future(operation())
        try:
            return await asyncio.shield(work)
        except asyncio.CancelledError:
            while not work.done():
                try:
                    await asyncio.shield(work)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
            # Retrieve any exception so a disconnected upload cannot emit an
            # unhandled-task warning. Cancellation remains the caller outcome.
            with suppress(BaseException):
                work.result()
            raise


def _parse_client_ids(value: str, file_count: int) -> list[uuid.UUID]:
    try:
        raw = json.loads(value)
        if not isinstance(raw, list) or len(raw) != file_count:
            raise ValueError
        ids = [uuid.UUID(item) for item in raw]
        if len(set(ids)) != len(ids):
            raise ValueError
        return ids
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(422, "Provide one distinct client_id for each file") from None


class EcrUpload(NamedTuple):
    """One immutable original file, identified before image or storage work."""

    client_id: uuid.UUID
    filename: str
    content_type: str
    sha256: str
    content: bytes


async def read_ecr_uploads(
    ids: list[uuid.UUID], files: list[UploadFile], limit: int
) -> list[EcrUpload]:
    uploads: list[EcrUpload] = []
    total = 0
    try:
        for client_id, file in zip(ids, files, strict=True):
            content = await file.read(limit + 1)
            total += len(content)
            if len(content) > limit or total > 20 * 1024 * 1024:
                raise HTTPException(
                    413, "Each image must be at most 10 MiB and each upload at most 20 MiB"
                )
            filename = (file.filename or "image").replace("\\", "/").rsplit("/", 1)[-1]
            filename = "".join((char for char in filename if ord(char) >= 32))[:255] or "image"
            uploads.append(
                EcrUpload(
                    client_id,
                    filename,
                    file.content_type or "application/octet-stream",
                    hashlib.sha256(content).hexdigest(),
                    content,
                )
            )
    finally:
        for file in files:
            await file.close()
    return uploads
