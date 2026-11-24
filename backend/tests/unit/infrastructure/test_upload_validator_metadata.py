"""Reported dimensions must describe the validated, canonical JPEG bytes."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.infrastructure.imports.passport_document_workspace import PassportDocumentImportWorkspace
from app.infrastructure.security.upload_validator import DisabledMalwareScanner, UploadValidator


def _source(orientation: int) -> bytes:
    output = io.BytesIO()
    with Image.new("RGB", (96, 48), "white") as picture:
        exif = Image.Exif()
        exif[274] = orientation
        picture.save(output, format="JPEG", exif=exif)
    return output.getvalue()


@pytest.mark.parametrize("orientation", [1, 6, 8])
@pytest.mark.parametrize("maximum", [None, 64])
def test_validated_metadata_matches_actual_oriented_and_bounded_image(orientation, maximum):
    result = UploadValidator(scanner=DisabledMalwareScanner()).validate(
        content=_source(orientation),
        filename="synthetic.jpg",
        declared_content_type="image/jpeg",
        max_dimension=maximum,
    )
    with Image.open(io.BytesIO(result.content)) as canonical:
        assert (result.width, result.height) == canonical.size
        assert canonical.getexif().get(274) is None
        if maximum is not None:
            assert max(canonical.size) <= maximum


@pytest.mark.parametrize("orientation", [6, 8])
def test_import_workspace_retains_metadata_for_exact_staged_canonical_image(orientation):
    result = UploadValidator(scanner=DisabledMalwareScanner()).validate(
        content=_source(orientation),
        filename="STF_SYNTH_FRONT.jpg",
        declared_content_type="image/jpeg",
    )
    with PassportDocumentImportWorkspace() as workspace:
        staged = workspace.stage(result)
        with Image.open(io.BytesIO(staged.read_content())) as canonical:
            assert (staged.width, staged.height) == canonical.size == (48, 96)
