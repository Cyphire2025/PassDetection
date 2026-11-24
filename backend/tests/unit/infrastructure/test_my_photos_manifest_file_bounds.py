"""The metadata byte cap still holds when a local file changes after preflight."""

import uuid
from pathlib import Path

import pytest

from scripts.register_my_photos_manifest import _MAX_MANIFEST_FILE_BYTES, _load_manifest
from tests.unit.infrastructure.test_my_photos_gallery_ingestion import _asset, _request


def _manifest():
    return _request(
        agency_id=uuid.uuid4(), group_id=uuid.uuid4(), manifest_identity="manifest-fixture",
        target_revision=1, assets=(_asset(0),), total_asset_count=1, batch_index=0,
    )


def test_valid_local_manifest_keeps_all_existing_metadata(tmp_path):
    expected = _manifest()
    path = tmp_path / "manifest.json"
    path.write_text(expected.model_dump_json(), encoding="utf-8")
    assert _load_manifest(path).model_dump() == expected.model_dump()


def test_growing_manifest_cannot_bypass_the_advertised_byte_limit(tmp_path, monkeypatch):
    expected = _manifest()
    path = tmp_path / "manifest.json"
    raw = expected.model_dump_json().encode("utf-8")
    path.write_bytes(raw)
    original_open = Path.open
    expanded = False

    def grow_before_read(current, *args, **kwargs):
        nonlocal expanded
        if current == path and not expanded:
            expanded = True
            with original_open(current, "wb") as target:
                target.write(raw + b" " * _MAX_MANIFEST_FILE_BYTES)
        return original_open(current, *args, **kwargs)

    monkeypatch.setattr(Path, "open", grow_before_read)
    with pytest.raises(ValueError, match="1 MiB"):
        _load_manifest(path)
    assert expanded
