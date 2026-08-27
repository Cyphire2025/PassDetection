from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import cast

from app.infrastructure.my_photos.development_fixture import _fixture_batch


def test_synthetic_gallery_generates_five_thousand_assets_in_bounded_batches() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    trip = SimpleNamespace(
        group=SimpleNamespace(id=group_id),
        access=SimpleNamespace(agency_id=agency_id),
    )
    gallery = SimpleNamespace(id=uuid.uuid4())

    asset_ids: set[uuid.UUID] = set()
    face_references: set[str] = set()
    asset_count = 0
    variant_count = 0
    face_count = 0
    portrait = landscape = square = offline = preparing = 0

    for start in range(0, 5_000, 250):
        assets, variants, faces = _fixture_batch(
            trip=trip,  # type: ignore[arg-type]
            gallery=gallery,  # type: ignore[arg-type]
            start=start,
            stop=start + 250,
        )
        assert len(assets) == 250
        assert len(variants) == 250
        assert len(faces) <= 300
        by_asset = {row["id"]: row for row in assets}
        for variant in variants:
            original = by_asset[variant["media_asset_id"]]
            assert cast("int", variant["byte_size"]) <= cast("int", original["byte_size"])
        for asset in assets:
            width = cast("int", asset["width"])
            height = cast("int", asset["height"])
            portrait += int(height > width)
            landscape += int(width > height)
            square += int(width == height)
            offline += int(asset["availability_state"] == "archived_offline")
            preparing += int(asset["availability_state"] == "preparing_delivery")
            asset_ids.add(asset["id"])  # type: ignore[arg-type]
        face_references.update(str(face["provider_face_reference"]) for face in faces)
        asset_count += len(assets)
        variant_count += len(variants)
        face_count += len(faces)

    assert asset_count == 5_000
    assert variant_count == 5_000
    assert face_count == 6_000
    assert len(asset_ids) == 5_000
    assert len(face_references) == 6_000
    assert portrait > 0 and landscape > 0 and square > 0
    assert offline > 0 and preparing > 0
    assert "dev-face-00000-primary" in face_references
    assert "dev-face-00000-secondary" in face_references
