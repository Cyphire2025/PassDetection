from __future__ import annotations

import asyncio
import unittest
import uuid
import zipfile
from pathlib import PurePosixPath

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


class ConcurrentStorage(FakeStorage):
    def __init__(self, objects: dict[str, bytes]) -> None:
        super().__init__(objects)
        self.active = 0
        self.peak_active = 0

    async def get_file(self, key: str) -> bytes:
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        try:
            await asyncio.sleep(0.01)
            return self.objects[key]
        finally:
            self.active -= 1


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
    def _submission(
        group: ClientGroup,
        *,
        include_selfie: bool,
        staff_code: str | None = None,
        agent_employee_type: str | None = None,
        agent_employee_code: str | None = None,
    ) -> PassportSubmission:
        submission = PassportSubmission.create(
            group_id=group.id,
            agency_id=group.agency_id,
            client_name="../Alex / Doe",
            client_email=None,
            image_s3_key=f"originals/{uuid.uuid4()}/front.JPG",
        )
        submission.passport_back_s3_key = f"originals/{uuid.uuid4()}/back.png"
        submission.passport_photo_s3_key = f"originals/{uuid.uuid4()}/selfie.jpeg" if include_selfie else None
        submission.confirmed_fields = {
            key: value
            for key, value in {
                "staff_code": staff_code,
                "agent_employee_type": agent_employee_type,
                "agent_employee_code": agent_employee_code,
            }.items()
            if value
        }
        return submission

    async def test_export_has_safe_deterministic_paths_and_collision_suffixes(self) -> None:
        group = self._group()
        first = self._submission(group, include_selfie=True, staff_code="01")
        second = self._submission(group, include_selfie=False, staff_code="01")
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
                self.assertTrue(any("STF_01_Alex _ Doe" in folder for folder in passenger_folders))
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

    async def test_export_uses_agent_employee_prefix_before_staff_code(self) -> None:
        group = self._group()
        agent = self._submission(
            group,
            include_selfie=False,
            staff_code="55",
            agent_employee_type="agent",
            agent_employee_code="123",
        )
        employee = self._submission(
            group,
            include_selfie=False,
            staff_code="66",
            agent_employee_type="employee",
            agent_employee_code="456",
        )
        employee.client_name = "Employee Name"
        submissions = [agent, employee]
        objects = {
            key: b"image"
            for submission in submissions
            for key in (submission.image_s3_key, submission.passport_back_s3_key)
            if key
        }

        spool, _, _ = await PassportImageZipExporter().export_group(
            submissions,
            group_name=group.name,
            staff_code_enabled=True,
            agent_employee_code_enabled=True,
            storage=FakeStorage(objects),  # type: ignore[arg-type]
        )
        try:
            with zipfile.ZipFile(spool) as archive:
                files = [name for name in archive.namelist() if not name.endswith("/")]
                self.assertTrue(any("AGT_123_Alex _ Doe" in name for name in files))
                self.assertTrue(any("EMP_456_Employee Name" in name for name in files))
                self.assertFalse(any("STF_55" in name or "STF_66" in name for name in files))
        finally:
            spool.close()

    async def test_export_places_passengers_in_exact_zone_folders(self) -> None:
        group = self._group()
        delhi = self._submission(group, include_selfie=False, staff_code="101")
        mumbai_one = self._submission(group, include_selfie=False, staff_code="102")
        mumbai_two = self._submission(group, include_selfie=False, staff_code="103")
        unassigned = self._submission(group, include_selfie=False, staff_code="104")
        delhi.client_name = "Delhi Person"
        mumbai_one.client_name = "Mumbai One Person"
        mumbai_two.client_name = "Mumbai Two Person"
        unassigned.client_name = "Unassigned Person"
        submissions = [unassigned, mumbai_two, delhi, mumbai_one]
        objects = {
            key: b"image"
            for submission in submissions
            for key in (submission.image_s3_key, submission.passport_back_s3_key)
            if key
        }

        spool, _, _ = await PassportImageZipExporter().export_group(
            submissions,
            group_name=group.name,
            staff_code_enabled=True,
            storage=FakeStorage(objects),  # type: ignore[arg-type]
            zone_names={
                delhi.id: "Delhi",
                mumbai_one.id: "Mumbai-1",
                mumbai_two.id: "Mumbai-2",
            },
        )
        try:
            with zipfile.ZipFile(spool) as archive:
                files = [name for name in archive.namelist() if not name.endswith("/")]
                self.assertTrue(any("/Delhi/STF_101_Delhi Person/" in name for name in files))
                self.assertTrue(any("/Mumbai-1/STF_102_Mumbai One Person/" in name for name in files))
                self.assertTrue(any("/Mumbai-2/STF_103_Mumbai Two Person/" in name for name in files))
                self.assertTrue(
                    any(
                        "/UNASSIGNED_ZONE/STF_104_Unassigned Person/" in name
                        for name in files
                    )
                )
                self.assertTrue(all(len(PurePosixPath(name).parts) == 4 for name in files))
        finally:
            spool.close()

    async def test_export_keeps_legacy_flat_layout_when_group_has_no_zones(self) -> None:
        group = self._group()
        submission = self._submission(group, include_selfie=False, staff_code="201")
        objects = {
            submission.image_s3_key: b"front",
            submission.passport_back_s3_key: b"back",
        }

        spool, _, _ = await PassportImageZipExporter().export_group(
            [submission],
            group_name=group.name,
            staff_code_enabled=True,
            storage=FakeStorage(objects),  # type: ignore[arg-type]
            zone_names={},
        )
        try:
            with zipfile.ZipFile(spool) as archive:
                files = [name for name in archive.namelist() if not name.endswith("/")]
                self.assertTrue(all(len(PurePosixPath(name).parts) == 3 for name in files))
                self.assertFalse(any("UNASSIGNED_ZONE" in name for name in files))
        finally:
            spool.close()

    async def test_export_sanitizes_colliding_zone_folder_names(self) -> None:
        group = self._group()
        slash_zone = self._submission(group, include_selfie=False)
        backslash_zone = self._submission(group, include_selfie=False)
        slash_zone.client_name = "Slash Zone Person"
        backslash_zone.client_name = "Backslash Zone Person"
        submissions = [slash_zone, backslash_zone]
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
            zone_names={
                slash_zone.id: "Delhi/West",
                backslash_zone.id: "Delhi\\West",
            },
        )
        try:
            with zipfile.ZipFile(spool) as archive:
                files = [name for name in archive.namelist() if not name.endswith("/")]
                zone_folders = {PurePosixPath(name).parts[1] for name in files}
                self.assertEqual(zone_folders, {"Delhi_West", "Delhi_West_2"})
                self.assertTrue(all(".." not in name and "\\" not in name for name in files))
        finally:
            spool.close()

    async def test_export_fetches_images_with_bounded_concurrency(self) -> None:
        group = self._group()
        submissions = [
            self._submission(group, include_selfie=True)
            for _ in range(4)
        ]
        objects = {
            key: key.encode()
            for submission in submissions
            for key in (
                submission.passport_photo_s3_key,
                submission.image_s3_key,
                submission.passport_back_s3_key,
            )
            if key
        }
        storage = ConcurrentStorage(objects)
        exporter = PassportImageZipExporter()

        spool, entry_count, total_bytes = await exporter.export_group(
            submissions,
            group_name=group.name,
            staff_code_enabled=False,
            storage=storage,  # type: ignore[arg-type]
        )
        try:
            self.assertEqual(entry_count, len(objects))
            self.assertEqual(
                total_bytes,
                sum(len(content) for content in objects.values()),
            )
            self.assertGreater(storage.peak_active, 1)
            self.assertLessEqual(
                storage.peak_active,
                exporter.STORAGE_FETCH_BATCH_SIZE,
            )
            with zipfile.ZipFile(spool) as archive:
                self.assertEqual(
                    len([name for name in archive.namelist() if not name.endswith("/")]),
                    len(objects),
                )
        finally:
            spool.close()


if __name__ == "__main__":
    unittest.main()
