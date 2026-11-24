"""Legacy manifest class identities retain their annotation and pickle namespace."""

import pickle
from typing import get_type_hints

import pytest

from app.infrastructure.my_photos import gallery_ingestion, gallery_manifest_contracts


@pytest.mark.parametrize(
    "name",
    [
        "GalleryManifestVariant",
        "GalleryManifestAsset",
        "GalleryManifestRequest",
        "GalleryManifestLocator",
        "GalleryManifestResult",
        "GalleryManifestStatus",
        "_VerifiedAsset",
    ],
)
def test_legacy_manifest_namespace_resolves_complete_type_contract(name):
    model = getattr(gallery_manifest_contracts, name)
    assert set(model.__annotations__) <= set(get_type_hints(model))
    assert model.__module__ == "app.infrastructure.my_photos.gallery_ingestion"
    assert getattr(gallery_ingestion, name) is model
    assert pickle.loads(pickle.dumps(model)) is model
