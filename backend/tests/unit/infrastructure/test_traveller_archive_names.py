"""Opaque retained keys yield usable archive names without another storage read."""

from unittest.mock import AsyncMock

import pytest

from app.infrastructure.export.passport_image_zip_exporter import (
    PassportImageZipExporter,
    _ArchiveImageSpec,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("content", "suffix"), [
    (b"\x89PNG\r\n\x1a\nsynthetic", ".png"), (b"\xff\xd8\xffsynthetic", ".jpg"),
    (b"RIFF1234WEBPsynthetic", ".webp"), (b"%PDF-1.7 synthetic", ".pdf"),
    (b"<html>not an image</html>", ".bin"),
])
async def test_retained_archive_name_uses_only_allowlisted_magic(content, suffix):
    storage = AsyncMock()
    storage.get_file.return_value = content
    result = await PassportImageZipExporter._load_image(
        _ArchiveImageSpec("Passenger/passport", "travellers/opaque/asset-id", None), storage=storage)
    assert result.path == "Passenger/passport" + suffix and result.content == content
    storage.get_file.assert_awaited_once()
