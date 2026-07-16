from __future__ import annotations

import uuid
import unittest
import zipfile

from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.infrastructure.export.passport_image_zip_exporter import (
    MissingPassportImagesError,
    PassportImageZipExporter,
)


class FakeStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    async def get_file(self, key: str) -> bytes:
        return self.objects[key]


class PassportImageZipExporterTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _group() -> ClientGroup:
        return ClientGroup.create(
            name="../Tour: 2026",
            token="public-group-token",
            agency_id=uuid.uuid4(),
            created_by_user_id=uuid.uuid4(),
        )

    @staticmethod
    def _submission(group: ClientGroup, *, include_selfie: bool, staff_code: str | None = None) -> PassportSubmission:
        submission = PassportSubmission.create(
            group_id=group.id,
            agency_id=group.agency_id,
            client_name="../Alex / Doe",
            client_email=None,
            image_s3_key=f"originals/{uuid.uuid4()}/front.JPG",
        )
        submission.passport_back_s3_key = f"originals/{uuid.uuid4()}/back.png"
        submission.passport_photo_s3_key = f"originals/{uuid.uuid4()}/selfie.jpeg" if include_selfie else None
        submission.confirmed_fields = {"staff_code": staff_code} if staff_code else {}
        return submission

    async def test_export_has_safe_deterministic_paths_and_collision_suffixes(self) -> None:
        group = self._group()
        first = self._submission(group, include_selfie=True, staff_code="STF/01")
        second = self._submission(group, include_selfie=False, staff_code="STF/01")
        objects = {
            first.image_s3_key: b"front-one",
            first.passport_back_s3_key: b"back-one",
            first.passport_photo_s3_key: b"selfie-one",
            second.image_s3_key: b"front-two",
            second.passport_back_s3_key: b"back-two",
        }

        spool, entry_count, total_bytes = await PassportImageZipExporter().export_group(
            [second, first],
            group_name=group.name,
            staff_code_enabled=True,
            storage=FakeStorage(objects),  # type: ignore[arg-type]
        )
        try:
            with zipfile.ZipFile(spool) as archive:
                names = archive.namelist()
                files = [name for name in names if not name.endswith("/")]
                self.assertEqual(entry_count, 5)
                self.assertEqual(total_bytes, sum(len(value) for value in objects.values()))
                self.assertTrue(all(".." not in name and "\\" not in name for name in names))
                self.assertEqual(sum(name.endswith("_visaimage.jpeg") for name in files), 1)
                self.assertEqual(sum(name.endswith("_passportfront.jpg") for name in files), 2)
                self.assertEqual(sum(name.endswith("_passportback.png") for name in files), 2)
                passenger_folders = {name.rsplit("/", 1)[0] for name in files}
                self.assertEqual(len(passenger_folders), 2)
                self.assertTrue(any(folder.endswith("_2") for folder in passenger_folders))
                self.assertEqual(archive.read(next(name for name in files if name.endswith("_visaimage.jpeg"))), b"selfie-one")
        finally:
            spool.close()

    async def test_export_rejects_missing_compulsory_originals(self) -> None:
        group = self._group()
        submission = self._submission(group, include_selfie=False)
        submission.passport_back_s3_key = None

        with self.assertRaises(MissingPassportImagesError):
            await PassportImageZipExporter().export_group(
                [submission],
                group_name=group.name,
                staff_code_enabled=False,
                storage=FakeStorage({}),  # type: ignore[arg-type]
            )

    async def test_export_reserves_folder_names_globally_and_ignores_staff_code_when_disabled(self) -> None:
        group = self._group()
        first = self._submission(group, include_selfie=False, staff_code="S1")
        duplicate = self._submission(group, include_selfie=False, staff_code="S2")
        literal_suffix = self._submission(group, include_selfie=False, staff_code="S3")
        first.client_name = "John"
        duplicate.client_name = "John"
        literal_suffix.client_name = "John_2"
        literal_suffix.image_s3_key = f"originals/{uuid.uuid4()}/front.exe"
        submissions = [first, duplicate, literal_suffix]
        objects = {
            key: b"image"
            for submission in submissions
            for key in (submission.image_s3_key, submission.passport_back_s3_key)
            if key
        }

        spool, _, _ = await PassportImageZipExporter().export_group(
            submissions,
            group_name=group.name,
            staff_code_enabled=False,
            storage=FakeStorage(objects),  # type: ignore[arg-type]
        )
        try:
            with zipfile.ZipFile(spool) as archive:
                files = [name for name in archive.namelist() if not name.endswith("/")]
                folders = {name.rsplit("/", 1)[0] for name in files}
                self.assertEqual(len(folders), 3)
                self.assertFalse(any("S1_" in name or "S2_" in name or "S3_" in name for name in files))
                self.assertTrue(any(name.endswith("John_passportfront.jpg") for name in files))
                self.assertTrue(any(name.endswith("John_2_passportfront.jpg") for name in files))
                self.assertTrue(any(name.endswith("John_2_2_passportfront.bin") for name in files))
        finally:
            spool.close()


if __name__ == "__main__":
    unittest.main()
