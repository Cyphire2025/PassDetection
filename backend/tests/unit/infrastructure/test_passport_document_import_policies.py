"""Real ZIP and canonical-spool controls for the import admission boundaries."""

from __future__ import annotations

import io
import stat
import struct
import zipfile

import pytest

from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.imports import passport_document_importer as importer
from app.infrastructure.imports import passport_document_workspace as workspace_owner
from app.infrastructure.imports import passport_zip_members as member_owner
from tests.unit.infrastructure.test_passport_document_import_staging import (
    _RecordingValidator,
    _source,
    _zip_source,
)


def collect(sources, *, validator=None):
    validator = validator or _RecordingValidator()
    with importer.PassportDocumentImportWorkspace() as workspace:
        accepted, rejected = importer.PassportDocumentImporter(validator).collect(
            sources, workspace=workspace, allowed_staff_codes={"A1"}
        )
        result = [
            (item.staff_code, item.document_type, item.upload.read_content()) for item in accepted
        ]
        errors = [(item.filename, item.reason) for item in rejected]
        return result, errors, validator.payloads, workspace.staged_bytes


@pytest.mark.parametrize(
    ("filename", "symlink", "reason"),
    [
        ("../STF_A1_FRONT.jpg", False, "Unsafe ZIP path"),
        ("/STF_A1_FRONT.jpg", False, "Unsafe ZIP path"),
        ("nested\\..\\STF_A1_FRONT.jpg", False, "Unsafe ZIP path"),
        ("STF_A1_FRONT.jpg", True, "ZIP symlink entries are not allowed"),
        ("unexpected.jpg", False, "Expected filename STF_<staffcode>_PHOTO"),
        ("STF_A2_FRONT.jpg", False, "Staff code was not found in this group"),
    ],
)
def test_unsafe_or_unmatched_entry_does_not_block_later_valid_image(filename, symlink, reason):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("nested/", b"")
        entry = zipfile.ZipInfo(filename)
        if symlink:
            entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(entry, b"rejected")
        archive.writestr("STF_A1_BACK.jpg", b"accepted")
    payload = stream.getvalue()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        archived_filename = archive.infolist()[1].filename
    result, errors, validated, staged = collect([_source("bundle.zip", payload)])
    assert result == [("A1", "back", b"canonical:accepted")]
    assert (
        len(errors) == 1 and errors[0][0] == archived_filename and errors[0][1].startswith(reason)
    )
    assert validated == [b"accepted"] and staged == len(b"canonical:accepted")


@pytest.mark.parametrize(
    ("filename", "reason"),
    [
        ("unexpected.jpg", "Expected filename STF_<staffcode>_PHOTO"),
        ("STF_A2_FRONT.jpg", "Staff code was not found in this group"),
    ],
)
def test_direct_name_policy_precedes_image_validation(filename, reason):
    result, errors, validated, staged = collect([_source(filename, b"untrusted")])
    assert result == [] and validated == [] and staged == 0
    assert len(errors) == 1 and errors[0][0] == filename and errors[0][1].startswith(reason)


def test_validation_rejection_preserves_later_archive_images():
    class RejectFirst(_RecordingValidator):
        def validate(self, **kwargs):
            if kwargs["content"] == b"reject":
                self.payloads.append(b"reject")
                raise ImageValidationError("Synthetic image rejection")
            return super().validate(**kwargs)

    result, errors, validated, staged = collect(
        [_zip_source({"STF_A1_FRONT.jpg": b"reject", "STF_A1_BACK.jpg": b"accept"})],
        validator=RejectFirst(),
    )
    assert result == [("A1", "back", b"canonical:accept")]
    assert errors == [("STF_A1_FRONT.jpg", "Synthetic image rejection")]
    assert validated == [b"reject", b"accept"] and staged == len(b"canonical:accept")


def test_staging_quota_keeps_prior_canonical_spool_and_rejects_only_failed_image(monkeypatch):
    monkeypatch.setattr(workspace_owner, "MAX_STAGED_CANONICAL_BYTES", 12)
    result, errors, validated, staged = collect(
        [_zip_source({"STF_A1_FRONT.jpg": b"a", "STF_A1_BACK.jpg": b"b"})]
    )
    assert result == [("A1", "front", b"canonical:a")]
    assert errors == [
        (
            "STF_A1_BACK.jpg",
            "Validated passport images exceed the bounded staging limit; split the import into smaller batches",
        )
    ]
    assert validated == [b"a", b"b"] and staged == len(b"canonical:a")


def test_cumulative_archive_quota_stops_before_later_filename_validation(monkeypatch):
    monkeypatch.setattr(member_owner, "MAX_UNCOMPRESSED_BYTES", 5)
    first = _zip_source({"STF_A1_FRONT.jpg": b"one"})
    second = _zip_source({"unexpected.jpg": b"two", "STF_A1_BACK.jpg": b"three"})
    second = importer.PassportDocumentUploadSource(
        "second.zip", second.stream, second.size_bytes, second.declared_content_type
    )
    result, errors, validated, staged = collect([first, second])
    assert result == [("A1", "front", b"canonical:one")]
    assert errors == [("second.zip", "ZIP imports exceed the 512 MB extracted-size staging limit")]
    assert validated == [b"one"] and staged == len(b"canonical:one")
    assert first.stream.tell() == 0 and second.stream.tell() == 0


@pytest.mark.parametrize("archive", [False, True])
def test_source_count_quota_keeps_first_source_and_never_validates_second(monkeypatch, archive):
    if archive:
        monkeypatch.setattr(importer, "MAX_ARCHIVES", 1)
        sources = [
            _zip_source({"STF_A1_FRONT.jpg": b"one"}),
            _zip_source({"STF_A1_BACK.jpg": b"two"}),
        ]
        expected = "Upload at most 1 ZIP archives at a time"
    else:
        monkeypatch.setattr(importer, "MAX_DIRECT_FILES", 1)
        sources = [_source("STF_A1_FRONT.jpg", b"one"), _source("STF_A1_BACK.jpg", b"two")]
        expected = "Upload at most 1 direct image files at a time"
    result, errors, validated, staged = collect(sources)
    assert result == [("A1", "front", b"canonical:one")]
    assert errors == [(sources[1].filename, expected)]
    assert validated == [b"one"] and staged == len(b"canonical:one")


@pytest.mark.parametrize("case", ["empty", "negative_size", "total_size"])
def test_whole_request_admission_precedes_source_reads(case):
    sources = (
        []
        if case == "empty"
        else [
            _source(
                "STF_A1_FRONT.jpg",
                b"a",
                declared_size=-1
                if case == "negative_size"
                else importer.MAX_TOTAL_SOURCE_BYTES + 1,
            )
        ]
    )
    result, errors, validated, staged = collect(sources)
    assert result == [] and validated == [] and staged == 0
    assert errors == (
        []
        if case == "empty"
        else [
            (
                "upload",
                "Upload size is invalid"
                if case == "negative_size"
                else "Upload exceeds the 256 MB request staging limit; split it into smaller batches",
            )
        ]
    )


@pytest.mark.parametrize("damage", ["encrypted", "crc", "oversized", "zero_compressed_size"])
def test_archive_metadata_failures_do_not_reach_image_validation(damage):
    source = _zip_source({"STF_A1_FRONT.jpg": b"synthetic-image"})
    payload = bytearray(source.stream.getvalue())
    central = payload.find(b"PK\x01\x02")
    assert central >= 0
    if damage == "encrypted":
        struct.pack_into("<H", payload, central + 8, 1)
        expected = "Encrypted ZIP archives are not allowed"
    elif damage == "crc":
        struct.pack_into("<L", payload, central + 16, 0)
        expected = "Unreadable or encrypted ZIP archive"
    elif damage == "oversized":
        struct.pack_into("<L", payload, central + 24, importer.MAX_MEMBER_BYTES + 1)
        expected = "Image exceeds the 20 MB per-file limit"
    else:
        struct.pack_into("<L", payload, central + 20, 0)
        expected = "Suspicious ZIP compression metadata"
    result, errors, validated, staged = collect([_source("bundle.zip", bytes(payload))])
    assert result == [] and validated == [] and staged == 0
    assert len(errors) == 1 and errors[0][1] == expected


def test_duplicate_identity_keeps_first_result_and_original_staging_accounting():
    result, errors, validated, staged = collect(
        [
            _source("STF_A1_FRONT.jpg", b"direct"),
            _zip_source({"nested/STF_A1_FRONT.jpg": b"zip", "STF_A1_BACK.jpg": b"back"}),
        ]
    )
    assert result == [("A1", "front", b"canonical:direct"), ("A1", "back", b"canonical:back")]
    assert errors == [("STF_A1_FRONT.jpg", "Duplicate document type for this staff code")]
    assert validated == [b"direct", b"zip", b"back"]
    assert staged == sum(len(b"canonical:" + item) for item in validated)
