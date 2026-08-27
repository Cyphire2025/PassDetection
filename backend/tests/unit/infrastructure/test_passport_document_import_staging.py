from __future__ import annotations

import io
import zipfile

import pytest

from app.infrastructure.imports import passport_document_importer as importer_module
from app.infrastructure.imports.passport_document_importer import (
    MAX_ARCHIVE_BYTES,
    MAX_COMPRESSION_RATIO,
    PassportDocumentImporter,
    PassportDocumentImportWorkspace,
    PassportDocumentUploadSource,
)
from app.infrastructure.security.upload_validator import ValidatedUpload


class _RecordingValidator:
    def __init__(self) -> None:
        self.payloads: list[bytes] = []

    def validate(
        self,
        *,
        content: bytes,
        filename: str | None,
        declared_content_type: str | None,
    ) -> ValidatedUpload:
        self.payloads.append(content)
        return ValidatedUpload(
            content=b"canonical:" + content,
            content_type="image/jpeg",
            filename=(filename or "passport") + ".canonical.jpg",
            width=10,
            height=10,
            format="JPEG",
        )


class _UnreadableOversizeStream(io.BytesIO):
    def read(self, *_: object, **__: object) -> bytes:
        raise AssertionError("oversize input body must not be read")


def _source(
    filename: str,
    content: bytes,
    *,
    declared_size: int | None = None,
    content_type: str | None = "image/jpeg",
) -> PassportDocumentUploadSource:
    return PassportDocumentUploadSource(
        filename=filename,
        stream=io.BytesIO(content),
        size_bytes=len(content) if declared_size is None else declared_size,
        declared_content_type=content_type,
    )


def _zip_source(
    members: dict[str, bytes],
    *,
    compression: int = zipfile.ZIP_STORED,
) -> PassportDocumentUploadSource:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=compression) as archive:
        for filename, content in members.items():
            archive.writestr(filename, content)
    payload = stream.getvalue()
    return _source("passport-bundle.zip", payload, content_type="application/zip")


def test_staged_import_reads_one_source_member_and_preserves_only_canonical_bytes() -> None:
    validator = _RecordingValidator()
    importer = PassportDocumentImporter(validator=validator)  # type: ignore[arg-type]
    sources = [
        _source("STF_A1_FRONT.jpg", b"direct-front"),
        _zip_source({"nested/STF_A1_PHOTO.png": b"archive-photo"}),
    ]

    with PassportDocumentImportWorkspace() as workspace:
        accepted, rejected = importer.collect(
            sources,
            workspace=workspace,
            allowed_staff_codes={"A1"},
        )

        assert rejected == []
        assert [(item.staff_code, item.document_type) for item in accepted] == [
            ("A1", "front"),
            ("A1", "photo"),
        ]
        assert [item.upload.read_content() for item in accepted] == [
            b"canonical:direct-front",
            b"canonical:archive-photo",
        ]
        assert validator.payloads == [b"direct-front", b"archive-photo"]
        assert workspace.staged_bytes == sum(item.upload.size_bytes for item in accepted)

    with pytest.raises(ValueError, match="closed file"):
        accepted[0].upload.read_content()


def test_oversize_source_is_rejected_before_any_body_read() -> None:
    validator = _RecordingValidator()
    importer = PassportDocumentImporter(validator=validator)  # type: ignore[arg-type]
    source = PassportDocumentUploadSource(
        filename="oversize.zip",
        stream=_UnreadableOversizeStream(),
        size_bytes=MAX_ARCHIVE_BYTES + 1,
        declared_content_type="application/zip",
    )

    with PassportDocumentImportWorkspace() as workspace:
        accepted, rejected = importer.collect([source], workspace=workspace)

    assert accepted == []
    assert rejected[0].reason == "File exceeds the 128 MB bounded import limit"
    assert validator.payloads == []


@pytest.mark.parametrize(
    ("content", "declared_size", "expected_error"),
    [
        (b"short", 10, "ended before its declared size"),
        (b"longer", 4, "exceeded its declared size"),
    ],
)
def test_direct_source_size_mismatch_fails_closed(
    content: bytes,
    declared_size: int,
    expected_error: str,
) -> None:
    validator = _RecordingValidator()
    importer = PassportDocumentImporter(validator=validator)  # type: ignore[arg-type]

    with PassportDocumentImportWorkspace() as workspace:
        accepted, rejected = importer.collect(
            [
                _source(
                    "STF_A1_FRONT.jpg",
                    content,
                    declared_size=declared_size,
                )
            ],
            workspace=workspace,
        )

    assert accepted == []
    assert expected_error in rejected[0].reason
    assert validator.payloads == []


def test_zip_bomb_ratio_is_rejected_without_decompression_or_validation() -> None:
    validator = _RecordingValidator()
    importer = PassportDocumentImporter(validator=validator)  # type: ignore[arg-type]
    source = _zip_source(
        {"STF_A1_FRONT.jpg": b"A" * (1024 * 1024)},
        compression=zipfile.ZIP_DEFLATED,
    )

    with zipfile.ZipFile(source.stream) as archive:
        member = archive.infolist()[0]
        assert member.file_size / member.compress_size > MAX_COMPRESSION_RATIO
    source.stream.seek(0)

    with PassportDocumentImportWorkspace() as workspace:
        accepted, rejected = importer.collect([source], workspace=workspace)

    assert accepted == []
    assert rejected[0].reason == "Suspicious ZIP compression ratio"
    assert validator.payloads == []


def test_workspace_staging_budget_and_truncated_spool_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importer_module, "MAX_STAGED_CANONICAL_BYTES", 12)
    workspace = PassportDocumentImportWorkspace()
    first = workspace.stage(
        ValidatedUpload(
            content=b"123456",
            content_type="image/jpeg",
            filename="first.jpg",
            width=1,
            height=1,
            format="JPEG",
        )
    )
    with pytest.raises(RuntimeError, match="bounded staging limit"):
        workspace.stage(
            ValidatedUpload(
                content=b"1234567",
                content_type="image/jpeg",
                filename="second.jpg",
                width=1,
                height=1,
                format="JPEG",
            )
        )

    first._stream.seek(0)  # noqa: SLF001
    first._stream.truncate(3)  # noqa: SLF001
    with pytest.raises(RuntimeError, match="ended before its declared size"):
        first.read_content()
    workspace.close()
