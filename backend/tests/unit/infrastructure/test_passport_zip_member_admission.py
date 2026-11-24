"""Reject excess ZIP directory records before allocating their ZipInfo objects."""

from __future__ import annotations

import io
import struct
import zipfile

import pytest

from app.infrastructure.imports import passport_document_importer as importer
from app.infrastructure.imports.passport_zip_admission import (
    PassportZipMemberLimitError,
    admit_passport_zip_directory,
)
from tests.unit.infrastructure.test_passport_document_import_staging import _RecordingValidator


def archive_bytes(*, entries, zip64=False, prefix=b"", comment=b""):
    output = io.BytesIO()
    original_limit = zipfile.ZIP_FILECOUNT_LIMIT
    try:
        if zip64:
            zipfile.ZIP_FILECOUNT_LIMIT = 0
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.comment = comment
            for filename, data in entries:
                archive.writestr(filename, data)
    finally:
        zipfile.ZIP_FILECOUNT_LIMIT = original_limit
    return prefix + output.getvalue()


def collect(payload):
    validator = _RecordingValidator()
    with importer.PassportDocumentImportWorkspace() as workspace:
        accepted, rejected = importer.PassportDocumentImporter(validator).collect(
            [
                importer.PassportDocumentUploadSource(
                    "synthetic.zip",
                    io.BytesIO(payload),
                    len(payload),
                    "application/zip",
                )
            ],
            workspace=workspace,
            allowed_staff_codes={"A1"},
        )
        actual = [
            (item.staff_code, item.document_type, item.upload.read_content()) for item in accepted
        ]
    return actual, rejected, validator.payloads


@pytest.mark.parametrize("zip64", [False, True])
@pytest.mark.parametrize("prefix", [b"", b"MZ-synthetic-prepended-bytes"])
def test_exact_limit_retains_canonical_images_comments_and_prefixed_zip64(
    monkeypatch, zip64, prefix
):
    monkeypatch.setattr(importer, "MAX_MEMBERS", 2)
    payload = archive_bytes(
        entries=[("nested/STF_A1_FRONT.jpg", b"front"), ("STF_A1_BACK.png", b"back")],
        zip64=zip64,
        prefix=prefix,
        comment=b"synthetic archive comment",
    )
    accepted, rejected, validated = collect(payload)
    assert rejected == []
    assert accepted == [("A1", "front", b"canonical:front"), ("A1", "back", b"canonical:back")]
    assert validated == [b"front", b"back"]


@pytest.mark.parametrize("zip64", [False, True])
@pytest.mark.parametrize("prefix", [b"", b"MZ-synthetic-prepended-bytes"])
def test_excess_records_are_rejected_before_any_zipinfo_allocation(monkeypatch, zip64, prefix):
    monkeypatch.setattr(importer, "MAX_MEMBERS", 2)
    payload = archive_bytes(
        entries=[
            ("nested/", b""),
            ("nested/STF_A1_FRONT.jpg", b"front"),
            ("STF_A1_BACK.png", b"back"),
        ],
        zip64=zip64,
        prefix=prefix,
        comment=b"synthetic archive comment",
    )
    original = zipfile.ZipInfo
    created = []

    class CountingZipInfo(original):
        def __init__(self, *args, **kwargs):
            created.append(True)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(zipfile, "ZipInfo", CountingZipInfo)
    accepted, rejected, validated = collect(payload)
    assert accepted == [] and validated == []
    assert len(rejected) == 1 and rejected[0].reason == "ZIP contains more than 2 entries"
    assert created == []


@pytest.mark.parametrize("claimed_count", [0, 1, 2])
def test_forged_end_record_count_cannot_bypass_actual_directory_admission(
    monkeypatch, claimed_count
):
    monkeypatch.setattr(importer, "MAX_MEMBERS", 2)
    payload = bytearray(archive_bytes(entries=[(f"synthetic-{i}.txt", b"") for i in range(3)]))
    end = payload.rfind(b"PK\x05\x06")
    assert end >= 0
    struct.pack_into("<HH", payload, end + 8, claimed_count, claimed_count)
    original = zipfile.ZipInfo
    created = []

    class CountingZipInfo(original):
        def __init__(self, *args, **kwargs):
            created.append(True)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(zipfile, "ZipInfo", CountingZipInfo)
    accepted, rejected, validated = collect(bytes(payload))
    assert accepted == [] and validated == []
    assert len(rejected) == 1 and rejected[0].reason == "ZIP contains more than 2 entries"
    assert created == []


def test_malformed_directory_retains_the_existing_unreadable_rejection():
    payload = bytearray(archive_bytes(entries=[("STF_A1_FRONT.jpg", b"front")]))
    central = payload.find(b"PK\x01\x02")
    assert central >= 0
    payload[central : central + 4] = b"BAD!"
    accepted, rejected, validated = collect(bytes(payload))
    assert accepted == [] and validated == []
    assert len(rejected) == 1 and rejected[0].reason == "Unreadable or encrypted ZIP archive"


@pytest.mark.parametrize("damage", ["negative_start", "short_directory", "oversized_name"])
def test_malformed_directory_bounds_fail_before_image_validation(damage):
    payload = bytearray(archive_bytes(entries=[("STF_A1_FRONT.jpg", b"front")]))
    central = payload.find(b"PK\x01\x02")
    end = payload.rfind(b"PK\x05\x06")
    assert central >= 0 and end >= 0
    if damage == "negative_start":
        struct.pack_into("<L", payload, end + 12, len(payload) + 1)
    elif damage == "short_directory":
        struct.pack_into("<L", payload, end + 12, 1)
    else:
        struct.pack_into("<H", payload, central + 28, 65535)
    accepted, rejected, validated = collect(bytes(payload))
    assert accepted == [] and validated == []
    assert len(rejected) == 1 and rejected[0].reason == "Unreadable or encrypted ZIP archive"


@pytest.mark.parametrize("limit", [1, 2])
def test_admission_restores_callers_cursor_on_success_and_quota_rejection(limit):
    payload = archive_bytes(entries=[("one.txt", b"one"), ("two.txt", b"two")])
    stream = io.BytesIO(payload)
    stream.seek(7)
    if limit == 1:
        with pytest.raises(PassportZipMemberLimitError, match="more than 1 entries"):
            admit_passport_zip_directory(stream, max_members=limit)
    else:
        admit_passport_zip_directory(stream, max_members=limit)
    assert stream.tell() == 7 and stream.read() == payload[7:]


def test_empty_archive_remains_a_successful_empty_import():
    accepted, rejected, validated = collect(archive_bytes(entries=[]))
    assert accepted == [] and rejected == [] and validated == []
