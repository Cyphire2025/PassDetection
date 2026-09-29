"""Transfer primitives used by explicit CLI commands and the typed artifact client.

Callers must supply paths explicitly authorized by the user. Remote content cannot
add paths to this allowlist. The caller completes export history only after this
module returns a verified receipt and the server acknowledges that receipt.
"""

import hashlib
import hmac
import os
import re
import stat
import uuid
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import anyio

from .config import ConnectorError

CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class FileReceipt:
    path: str
    size_bytes: int
    sha256: str


async def provided_file_chunks(
    path: Path, *, allowed_paths: frozenset[Path], max_bytes: int
) -> AsyncIterator[bytes]:
    """Read one explicitly provided regular file with bounded memory and size."""
    if not path.is_absolute():
        raise ConnectorError("This upload path was not explicitly provided for this transfer.")
    resolved = path.resolve(strict=True)
    if resolved not in allowed_paths:
        raise ConnectorError("This upload path was not explicitly provided for this transfer.")
    expected = resolved.stat(follow_symlinks=False)
    if not stat.S_ISREG(expected.st_mode):
        raise ConnectorError("The provided upload must be a regular file.")
    # A server response is never accepted as an allowed_paths value.
    async with await anyio.open_file(resolved, "rb") as source:
        before = os.fstat(source.fileno())
        if (before.st_dev, before.st_ino) != (expected.st_dev, expected.st_ino):
            raise ConnectorError("The provided file changed before it could be opened safely.")
        if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
            raise ConnectorError(
                "The provided upload is not a permitted regular file or is too large."
            )
        sent = 0
        while chunk := await source.read(CHUNK_SIZE):
            sent += len(chunk)
            if sent > max_bytes:
                raise ConnectorError("The provided file exceeded the upload size limit.")
            yield chunk
        after = os.fstat(source.fileno())
        if (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ) or sent != before.st_size:
            raise ConnectorError(
                "The file changed during upload. Discard the staged transfer and retry explicitly."
            )


async def save_verified_download(
    chunks: AsyncIterable[bytes],
    *,
    destination: Path,
    expected_size: int,
    expected_sha256: str,
    max_bytes: int,
) -> FileReceipt:
    """Publish a complete verified local file atomically without replacing an existing file."""
    if (
        not destination.is_absolute()
        or not destination.parent.is_dir()
        or not 0 <= expected_size <= max_bytes
        or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256)
    ):
        raise ConnectorError(
            "A valid explicit destination and artifact checksum/size are required."
        )
    if destination.exists():
        raise ConnectorError("The destination already exists. Choose a different filename.")
    temporary = destination.parent / f".gcmcp-{uuid.uuid4().hex}.part"
    size, digest = 0, hashlib.sha256()
    try:
        async with await anyio.open_file(temporary, "xb") as output:
            async for chunk in chunks:
                size += len(chunk)
                if size > expected_size or size > max_bytes:
                    raise ConnectorError("Downloaded content exceeds the authorized artifact size.")
                digest.update(chunk)
                await output.write(chunk)
            if size != expected_size or not hmac.compare_digest(
                digest.hexdigest(), expected_sha256.lower()
            ):
                raise ConnectorError(
                    "Download verification failed; export delivery was not completed."
                )
            await output.flush()
            await anyio.to_thread.run_sync(os.fsync, output.fileno())
        try:
            # Unlike replace/rename on some platforms, link creation cannot overwrite a raced destination.
            await anyio.to_thread.run_sync(os.link, temporary, destination)
        except FileExistsError:
            raise ConnectorError(
                "The destination was created during download. Choose a different filename."
            ) from None
        except OSError:
            raise ConnectorError(
                "This filesystem cannot safely publish the download without overwriting. Choose a local supported filesystem."
            ) from None
        return FileReceipt(str(destination), size, digest.hexdigest())
    finally:
        # This private transfer copy is disposable; source documents/business records are untouched.
        temporary.unlink(missing_ok=True)
