import hashlib

import pytest

from gc_mcp_connector.config import ConnectorError
from gc_mcp_connector.files import provided_file_chunks, save_verified_download


async def chunks(*parts):
    for part in parts:
        yield part


async def test_verified_download_returns_checksum_and_never_overwrites(tmp_path):
    destination = tmp_path / "group.xlsx"
    data = b"verified-export-data"
    digest = hashlib.sha256(data).hexdigest()
    receipt = await save_verified_download(
        chunks(data[:5], data[5:]),
        destination=destination,
        expected_size=len(data),
        expected_sha256=digest,
        max_bytes=1000,
    )
    assert receipt.size_bytes == len(data)
    assert receipt.sha256 == digest
    assert destination.read_bytes() == data
    with pytest.raises(ConnectorError, match="already exists"):
        await save_verified_download(
            chunks(b"replace"),
            destination=destination,
            expected_size=7,
            expected_sha256=digest,
            max_bytes=1000,
        )
    assert destination.read_bytes() == data


async def test_corrupt_interrupted_and_raced_downloads_never_report_completion(tmp_path):
    destination = tmp_path / "group.xlsx"
    for source in (chunks(b"incorrect"), chunks(b"short")):
        with pytest.raises(ConnectorError, match="verification failed"):
            await save_verified_download(
                source,
                destination=destination,
                expected_size=9,
                expected_sha256="0" * 64,
                max_bytes=1000,
            )
        assert not destination.exists()
        assert not list(tmp_path.glob("*.part"))

    async def raced():
        destination.write_bytes(b"existing-user-content")
        yield b"new"

    with pytest.raises(ConnectorError, match="created during download"):
        await save_verified_download(
            raced(),
            destination=destination,
            expected_size=3,
            expected_sha256=hashlib.sha256(b"new").hexdigest(),
            max_bytes=1000,
        )
    assert destination.read_bytes() == b"existing-user-content"


async def test_only_explicit_provided_regular_files_can_be_streamed(tmp_path):
    provided = tmp_path / "provided.xlsx"
    provided.write_bytes(b"source-data")
    other = tmp_path / "unrelated.xlsx"
    other.write_bytes(b"do-not-read")
    allowed = frozenset({provided.resolve()})
    assert (
        b"".join(
            [
                chunk
                async for chunk in provided_file_chunks(
                    provided, allowed_paths=allowed, max_bytes=100
                )
            ]
        )
        == b"source-data"
    )
    with pytest.raises(ConnectorError, match="not explicitly provided"):
        _ = [
            chunk
            async for chunk in provided_file_chunks(other, allowed_paths=allowed, max_bytes=100)
        ]
    with pytest.raises(ConnectorError, match="too large"):
        _ = [
            chunk
            async for chunk in provided_file_chunks(provided, allowed_paths=allowed, max_bytes=2)
        ]


async def test_interrupted_transfer_removes_only_its_private_copy(tmp_path):
    destination = tmp_path / "unfinished.zip"

    async def interrupted():
        yield b"part"
        raise RuntimeError("interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        await save_verified_download(
            interrupted(),
            destination=destination,
            expected_size=9,
            expected_sha256="0" * 64,
            max_bytes=100,
        )
    assert not destination.exists()
    assert list(tmp_path.iterdir()) == []
