from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.storage.minio_repository import MinioStorageRepository


class _Body:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.offset = 0
        self.read_sizes: list[int] = []
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class _Client:
    def __init__(
        self,
        payload: bytes,
        *,
        include_length: bool = True,
        head_length: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self.payload = payload
        self.include_length = include_length
        self.head_length = len(payload) if head_length is None else head_length
        self.metadata = metadata or {}
        self.requests: list[dict[str, str]] = []
        self.head_requests: list[dict[str, str]] = []
        self.put_requests: list[dict[str, object]] = []
        self.bodies: list[_Body] = []

    def head_object(self, **kwargs: str) -> dict[str, object]:
        self.head_requests.append(kwargs)
        return {
            "ContentLength": self.head_length,
            "ContentType": "application/pdf",
            "Metadata": self.metadata,
        }

    def put_object(self, **kwargs: object) -> None:
        self.put_requests.append(kwargs)

    def get_object(self, **kwargs: str) -> dict[str, object]:
        self.requests.append(kwargs)
        range_value = kwargs["Range"]
        bounds = range_value.removeprefix("bytes=").split("-", maxsplit=1)
        start = int(bounds[0])
        end = int(bounds[1]) if bounds[1] else len(self.payload) - 1
        body = _Body(self.payload[start : end + 1])
        self.bodies.append(body)
        response: dict[str, object] = {"Body": body}
        if self.include_length:
            response["ContentLength"] = len(body.payload)
        return response


def _repository(client: _Client) -> MinioStorageRepository:
    repository = object.__new__(MinioStorageRepository)
    repository.settings = SimpleNamespace(bucket_name="private")
    repository._client = client
    repository._presign_client = client
    return repository


@pytest.mark.asyncio
async def test_upload_file_persists_sha256_in_private_object_metadata() -> None:
    payload = b"%PDF-1.7\nprivate"
    client = _Client(b"")
    repository = _repository(client)

    key = await repository.upload_file(payload, "documents/file.pdf", "application/pdf")

    assert key == "documents/file.pdf"
    assert client.put_requests == [
        {
            "Bucket": "private",
            "Key": "documents/file.pdf",
            "Body": payload,
            "ContentType": "application/pdf",
            "Metadata": {"sha256": hashlib.sha256(payload).hexdigest()},
        }
    ]


@pytest.mark.asyncio
async def test_stat_file_uses_stored_checksum_without_getting_body() -> None:
    payload = b"%PDF-1.7\nprivate"
    checksum = hashlib.sha256(payload).hexdigest()
    client = _Client(payload, metadata={"sha256": checksum.upper()})
    repository = _repository(client)

    metadata = await repository.stat_file("documents/file.pdf")

    assert metadata.size_bytes == len(payload)
    assert metadata.checksum_sha256 == checksum
    assert metadata.content_type == "application/pdf"
    assert client.head_requests == [{"Bucket": "private", "Key": "documents/file.pdf"}]
    assert client.requests == []
    assert client.bodies == []


@pytest.mark.asyncio
async def test_stat_file_missing_length_fails_closed() -> None:
    client = _Client(b"")
    repository = _repository(client)
    client.head_object = lambda **_kwargs: {"Metadata": {}}  # type: ignore[method-assign]

    with pytest.raises(StorageError, match="safe content length"):
        await repository.stat_file("documents/missing-size.pdf")


@pytest.mark.asyncio
async def test_stat_file_missing_object_fails_closed() -> None:
    client = _Client(b"")
    repository = _repository(client)

    def missing(**_kwargs: str) -> dict[str, object]:
        raise FileNotFoundError("private object is missing")

    client.head_object = missing  # type: ignore[method-assign]

    with pytest.raises(StorageError, match="temporarily unavailable"):
        await repository.stat_file("documents/missing.pdf")


@pytest.mark.asyncio
async def test_legacy_sha256_hashing_reads_only_bounded_chunks() -> None:
    payload = b"%PDF-1.7\n" + (b"x" * 25_000)
    client = _Client(payload)
    repository = _repository(client)

    checksum = await repository.calculate_file_sha256(
        "documents/legacy.pdf",
        expected_bytes=len(payload),
        chunk_size=1024,
    )

    assert checksum == hashlib.sha256(payload).hexdigest()
    assert max(client.bodies[0].read_sizes) <= 1024
    assert client.bodies[0].closed is True


@pytest.mark.asyncio
async def test_legacy_sha256_hashing_rejects_truncated_stream() -> None:
    client = _Client(b"%PDF-short", include_length=False, head_length=100)
    repository = _repository(client)

    with pytest.raises(StorageError, match="ended unexpectedly"):
        await repository.calculate_file_sha256(
            "documents/truncated.pdf",
            expected_bytes=100,
            chunk_size=1024,
        )

    assert client.bodies[0].closed is True


@pytest.mark.asyncio
async def test_stream_file_uses_bounded_object_range_and_chunks() -> None:
    payload = bytes(range(251)) * 40
    client = _Client(payload)
    repository = _repository(client)

    chunks = [
        chunk
        async for chunk in repository.stream_file(
            "documents/passport.bin",
            start=125,
            expected_bytes=len(payload) - 125,
            chunk_size=1024,
        )
    ]

    assert b"".join(chunks) == payload[125:]
    assert client.requests == [
        {"Bucket": "private", "Key": "documents/passport.bin", "Range": "bytes=125-"}
    ]
    assert max(client.bodies[0].read_sizes) <= 1024
    assert client.bodies[0].closed is True


@pytest.mark.asyncio
async def test_stream_file_without_content_length_rejects_trailing_bytes() -> None:
    client = _Client(b"0123456789", include_length=False)
    repository = _repository(client)

    with pytest.raises(StorageError, match="authorized size"):
        _ = [
            chunk
            async for chunk in repository.stream_file(
                "documents/file.bin",
                start=0,
                expected_bytes=8,
                chunk_size=1024,
            )
        ]

    assert client.bodies[0].closed is True


@pytest.mark.asyncio
async def test_get_file_range_never_reads_the_full_object() -> None:
    payload = b"%PDF-1.7" + (b"x" * 100_000)
    client = _Client(payload)
    repository = _repository(client)

    prefix = await repository.get_file_range("documents/file.pdf", start=0, end=15)

    assert prefix == payload[:16]
    assert client.requests[0]["Range"] == "bytes=0-15"
    assert client.bodies[0].read_sizes == [17]
    assert client.bodies[0].closed is True
