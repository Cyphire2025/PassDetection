"""Preview does not trust mismatched or duplicate extractor output or unreadable spools."""

import io
from types import SimpleNamespace

import pytest
from fastapi import UploadFile

from app.infrastructure.imports.passport_document_importer import (
    PassportDocumentFile,
    PassportDocumentImportWorkspace,
)
from app.infrastructure.security.upload_validator import ValidatedUpload
from app.presentation.api.v1.routes.passport_routes import document_import_preview as owner
from tests.unit.presentation.passport_document_import_fixture import install_import_context


async def test_preview_filters_unknown_staff_and_duplicate_document_records(monkeypatch):
    context = install_import_context(monkeypatch)
    with PassportDocumentImportWorkspace() as workspace:
        staged = workspace.stage(
            ValidatedUpload(
                content=b"synthetic-canonical",
                content_type="image/jpeg",
                filename="front.jpg",
                width=100,
                height=100,
                format="JPEG",
            )
        )
        records = [
            PassportDocumentFile("first.jpg", "A1", "front", staged),
            PassportDocumentFile("duplicate.jpg", "A1", "front", staged),
            PassportDocumentFile("other.jpg", "OTHER", "front", staged),
        ]
        # The upstream parser already filters staff IDs; this deliberately violates
        # that boundary to exercise preview's own independent final mapping guard.
        monkeypatch.setattr(
            owner,
            "PassportDocumentImporter",
            lambda: SimpleNamespace(
                collect=lambda *_args, **_kwargs: (records, []),
            ),
        )
        response, matched = await owner._passport_document_preview(
            group_id=context.group.id,
            files=[],
            session=context.session,
            workspace=workspace,
        )
    assert matched == [records[0]] and response.accepted_count == 1
    assert response.accepted_documents[0].passenger_id == context.submission.id
    assert response.rejected_count == 2
    assert {value.reason for value in response.rejected_documents} == {
        "Duplicate document type for this passenger",
        "Staff code was not found in this group",
    }


@pytest.mark.parametrize("error", [OSError, ValueError])
async def test_failed_spool_measurement_carries_an_invalid_size_without_reading_body(error):
    class FailedSpool(io.BytesIO):
        def seek(self, *_args):
            raise error("Synthetic closed or failed spool")

    upload = UploadFile(FailedSpool(b"private-synthetic-body"))
    try:
        result = owner._passport_document_upload_sources([upload])
        assert len(result) == 1 and result[0].size_bytes == -1
        assert result[0].filename == "upload"
    finally:
        await upload.close()
