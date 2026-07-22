from __future__ import annotations

import io
import uuid
import zipfile

from PIL import Image

from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.domain.exceptions.exceptions import StorageError
from app.domain.value_objects.passport_image_crop import PassportImageCrop, PassportImageType
from app.infrastructure.export.passport_image_zip_exporter import PassportImageZipExporter


def _jpeg(width: int, height: int, color: str = "green") -> bytes:
    image = Image.new("RGB", (width, height), color)
    output = io.BytesIO()
    image.save(output, format="JPEG")
    image.close()
    return output.getvalue()


class _Storage:
    def __init__(self, objects: dict[str, bytes], *, failing: set[str] | None = None) -> None:
        self.objects = objects
        self.failing = failing or set()

    async def get_file(self, key: str) -> bytes:
        if key in self.failing:
            raise StorageError("missing derivative")
        return self.objects[key]


def _submission() -> PassportSubmission:
    group = ClientGroup.create(
        name="Crop Export",
        token="crop-export-token",
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
    )
    submission = PassportSubmission.create(
        group_id=group.id,
        agency_id=group.agency_id,
        client_name="Crop Person",
        client_email=None,
        image_s3_key="original/front.jpg",
    )
    submission.passport_back_s3_key = "original/back.jpg"
    return submission


def _crop(submission: PassportSubmission) -> PassportImageCrop:
    return PassportImageCrop(
        submission_id=submission.id,
        image_type=PassportImageType.PASSPORT_FRONT,
        source_storage_key=submission.image_s3_key,
        derived_storage_key="derived/front-r1.jpg",
        active=True,
        x=0.25,
        y=0.25,
        width=0.5,
        height=0.5,
        rotation_degrees=0,
        source_width=400,
        source_height=300,
        revision=1,
    )


async def _export(storage: _Storage, submission: PassportSubmission, crop: PassportImageCrop):
    return await PassportImageZipExporter().export_group(
        [submission],
        group_name="Crop Export",
        staff_code_enabled=False,
        storage=storage,  # type: ignore[arg-type]
        crop_metadata={submission.id: {crop.image_type: crop}},
    )


async def test_zip_uses_materialized_effective_crop() -> None:
    submission = _submission()
    crop = _crop(submission)
    storage = _Storage(
        {
            submission.image_s3_key: _jpeg(400, 300),
            submission.passport_back_s3_key: b"back",
            crop.derived_storage_key: b"materialized-crop",  # type: ignore[dict-item]
        }
    )
    spool, _, _ = await _export(storage, submission, crop)
    try:
        with zipfile.ZipFile(spool) as archive:
            front_name = next(name for name in archive.namelist() if name.endswith("_passportfront.jpg"))
            assert archive.read(front_name) == b"materialized-crop"
    finally:
        spool.close()


async def test_zip_renders_from_immutable_source_if_snapshotted_derivative_was_cleaned() -> None:
    submission = _submission()
    crop = _crop(submission)
    storage = _Storage(
        {
            submission.image_s3_key: _jpeg(400, 300),
            submission.passport_back_s3_key: b"back",
        },
        failing={crop.derived_storage_key},  # type: ignore[arg-type]
    )
    spool, _, _ = await _export(storage, submission, crop)
    try:
        with zipfile.ZipFile(spool) as archive:
            front_name = next(name for name in archive.namelist() if name.endswith("_passportfront.jpg"))
            with Image.open(io.BytesIO(archive.read(front_name))) as rendered:
                assert rendered.size == (200, 150)
    finally:
        spool.close()


async def test_zip_renders_from_ai_edit_source_if_derivative_was_cleaned() -> None:
    submission = _submission()
    submission.passport_photo_s3_key = "original/visa.jpg"
    crop = PassportImageCrop(
        submission_id=submission.id,
        image_type=PassportImageType.VISA_PHOTO,
        source_storage_key=submission.passport_photo_s3_key,
        edit_source_storage_key="passport-edits/visa-ai-r1.jpg",
        derived_storage_key="derived/visa-r1.jpg",
        active=True,
        x=0.25,
        y=0.25,
        width=0.5,
        height=0.5,
        rotation_degrees=0,
        source_width=600,
        source_height=600,
        revision=1,
    )
    storage = _Storage(
        {
            submission.image_s3_key: b"front",
            submission.passport_back_s3_key: b"back",
            submission.passport_photo_s3_key: _jpeg(600, 600),
            crop.edit_source_storage_key: _jpeg(600, 600, "blue"),  # type: ignore[dict-item]
        },
        failing={crop.derived_storage_key},  # type: ignore[arg-type]
    )

    spool, _, _ = await _export(storage, submission, crop)
    try:
        with zipfile.ZipFile(spool) as archive:
            visa_name = next(
                name
                for name in archive.namelist()
                if name.endswith("_visaimage.jpg")
            )
            with Image.open(io.BytesIO(archive.read(visa_name))) as rendered:
                # The 50% crop must come from the blue AI source, not the
                # green immutable upload.
                assert rendered.size == (300, 300)
                red, green, blue = rendered.getpixel((150, 150))
                assert blue > 200
                assert red < 40
                assert green < 40
    finally:
        spool.close()
