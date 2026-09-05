from __future__ import annotations

import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from httpx import ASGITransport, AsyncClient

from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.domain.entities.entities import ClientGroup
from app.domain.value_objects.upload_configuration import MAX_PUBLIC_DOCUMENT_BYTES
from app.presentation.api.v1.routes.passport_routes import (
    public_security,
    public_upload,
    submission_review,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    ClientSubmitPassportRequest,
    PassportSubmissionResponse,
)


@pytest.mark.parametrize("size", [MAX_PUBLIC_DOCUMENT_BYTES, MAX_PUBLIC_DOCUMENT_BYTES + 1])
async def test_device_document_size_limit_runs_before_decoder(monkeypatch, size):
    upload = UploadFile(file=io.BytesIO(b"x" * size), filename="synthetic.jpg")
    security = Mock(validate_image=AsyncMock(return_value=object()))
    monkeypatch.setattr(public_security, "UploadSecurityService", Mock(return_value=security))
    monkeypatch.setattr(public_security, "get_settings", lambda: SimpleNamespace(upload_max_file_size_bytes=16 * 1024 * 1024))
    if size > MAX_PUBLIC_DOCUMENT_BYTES:
        with pytest.raises(HTTPException, match="2 MB") as exc:
            await public_security._validated_upload_file(upload, label="passport front cover", max_size_bytes=MAX_PUBLIC_DOCUMENT_BYTES)
        assert exc.value.status_code == 400
        security.validate_image.assert_not_awaited()
    else:
        await public_security._validated_upload_file(upload, label="passport front cover", max_size_bytes=MAX_PUBLIC_DOCUMENT_BYTES)
        security.validate_image.assert_awaited_once()
    assert upload.file.closed


async def test_disabled_live_scan_is_rejected_before_any_file_decode(monkeypatch):
    group = ClientGroup.create(
        "Configured link", "synthetic-link", uuid.uuid4(), uuid.uuid4(),
        upload_configuration={"passport_live_scan": False},
    )
    monkeypatch.setattr(public_upload, "ClientGroupRepository", lambda _: Mock(get_by_token=AsyncMock(return_value=group)))
    monkeypatch.setattr(public_upload, "upload_session_matches_identifier", lambda *_: True)
    decode = AsyncMock()
    monkeypatch.setattr(public_upload, "_validated_upload_file", decode)
    front = UploadFile(file=io.BytesIO(b"untrusted"), filename="front.jpg")
    back = UploadFile(file=io.BytesIO(b"untrusted"), filename="back.jpg")
    with pytest.raises(HTTPException, match="disabled") as exc:
        await public_upload.upload_passport(
            token=group.token, background_tasks=BackgroundTasks(), client_name="Traveller",
            acquisition_mode="camera", upload_idempotency_key="a" * 40, upload_session_id="a" * 40,
            qualifier_selection_token=None, file=front, passport_back_file=back, passport_photo_file=None,
            passport_cover_file=None, passport_back_cover_file=None, visa_photo_source=None,
            use_case=Mock(), session=AsyncMock(),
        )
    assert exc.value.status_code == 400
    decode.assert_not_awaited()
    assert front.file.tell() == 0


async def test_details_only_final_submit_commits_without_verification_job(monkeypatch):
    submission_id = uuid.uuid4()
    credential = "synthetic-upload-session-" + "a" * 40
    existing = SimpleNamespace(upload_idempotency_key=credential)
    monkeypatch.setattr(submission_review, "PassportSubmissionRepository", lambda _: Mock(get_by_id=AsyncMock(return_value=existing)))
    verification_repo = Mock(enqueue=AsyncMock())
    monkeypatch.setattr(submission_review, "PostSubmissionVerificationJobRepository", lambda _: verification_repo)
    result = SimpleNamespace(
        id=submission_id, image_s3_key="", idempotent_replay=True,
        agency_id=uuid.uuid4(), group_id=uuid.uuid4(),
        post_submission_verification_revision=1, storage_cleanup_keys=(),
    )
    expected = object()
    monkeypatch.setattr(PassportSubmissionResponse, "model_validate", lambda _: expected)
    session = AsyncMock()
    response = await submission_review.client_submit_passport(
        submission_id=submission_id,
        body=ClientSubmitPassportRequest(group_token="synthetic-configured-upload-link", confirmed_fields={"given_names": "Synthetic Traveller"}),
        background_tasks=BackgroundTasks(), upload_session_id=credential,
        use_case=Mock(execute=AsyncMock(return_value=result)), session=session,
    )
    assert response is expected
    session.commit.assert_awaited_once()
    verification_repo.enqueue.assert_not_awaited()


async def test_multipart_endpoint_accepts_and_commits_a_details_only_draft(monkeypatch):
    group = ClientGroup.create(
        "Details only", "synthetic-link", uuid.uuid4(), uuid.uuid4(),
        upload_configuration={"passport_enabled": False},
    )
    groups = Mock(get_by_token=AsyncMock(return_value=group))
    passports = AsyncMock()
    passports.get_by_upload_idempotency_key.return_value = None
    passports.save_idempotent.side_effect = lambda value: (value, True)
    storage = AsyncMock()
    use_case = SubmitPassportUseCase(groups, passports, storage)
    session = AsyncMock()
    monkeypatch.setattr(public_upload, "ClientGroupRepository", lambda _: groups)
    monkeypatch.setattr(public_upload, "propagate_mobile_passenger_change", AsyncMock())

    async def response_from_dto(result, **_kwargs):
        session.commit.assert_awaited_once()
        return PassportSubmissionResponse.model_validate(result)

    monkeypatch.setattr(public_upload, "_response_from_dto", response_from_dto)
    app = FastAPI()
    app.include_router(public_upload.router)
    app.dependency_overrides[public_upload._get_submit_passport_use_case] = lambda: use_case
    app.dependency_overrides[public_upload.get_db_session] = lambda: session
    credential = "synthetic-upload-" + "a" * 40
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/upload/synthetic-link",
            data={"client_name": "Synthetic Traveller", "acquisition_mode": "file", "upload_idempotency_key": credential},
            headers={"X-Upload-Session-ID": credential},
        )
    assert response.status_code == 201, response.text
    assert response.json()["image_s3_key"] == ""
    assert response.json()["extraction_status"] == "ready_for_review"
    assert response.json()["processing_job_id"] is None
    storage.upload_file.assert_not_awaited()
