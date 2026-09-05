from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile

from app.domain.entities.entities import ClientGroup, GroupStatus
from app.presentation.api.v1.routes.passport_routes import public_upload


def _group(state: GroupStatus) -> ClientGroup:
    return ClientGroup(
        id=uuid.uuid4(),
        name="Synthetic event",
        token="synthetic-link",
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        status=state,
    )


@pytest.mark.parametrize(
    "state", [GroupStatus.CLOSED, GroupStatus.ARCHIVED, GroupStatus.DELETED, None]
)
@pytest.mark.parametrize("endpoint", ["status", "image", "document", "scan", "discard"])
async def test_inactive_link_cannot_reach_submission_or_storage(
    monkeypatch: pytest.MonkeyPatch, state: GroupStatus | None, endpoint: str
) -> None:
    group = _group(state) if state is not None else None
    groups = Mock(get_by_token=AsyncMock(return_value=group))
    submissions = Mock()
    storage = Mock()
    monkeypatch.setattr(public_upload, "ClientGroupRepository", Mock(return_value=groups))
    monkeypatch.setattr(public_upload, "PassportSubmissionRepository", submissions)
    monkeypatch.setattr(public_upload, "MinioStorageRepository", storage)
    arguments = dict(
        token="synthetic-link",
        submission_id=uuid.uuid4(),
        upload_session_id="a" * 40,
        session=AsyncMock(),
    )
    handlers = {
        "status": public_upload.get_upload_passport_status,
        "image": public_upload.get_public_upload_passport_image,
        "document": public_upload.get_public_upload_passport_document,
        "scan": public_upload.scan_again_public_upload,
        "discard": public_upload.discard_public_upload,
    }
    if endpoint in {"status", "scan"}:
        arguments["background_tasks"] = BackgroundTasks()
    if endpoint == "scan":
        arguments["use_case"] = Mock()
    if endpoint == "document":
        arguments["document_type"] = "back"
    with pytest.raises(HTTPException) as exc:
        await handlers[endpoint](**arguments)
    assert exc.value.status_code == 404
    submissions.assert_not_called()
    storage.assert_not_called()


@pytest.mark.parametrize(
    "state", [GroupStatus.CLOSED, GroupStatus.ARCHIVED, GroupStatus.DELETED, None]
)
async def test_invalid_upload_link_is_rejected_before_file_read_or_decode(
    monkeypatch: pytest.MonkeyPatch, state: GroupStatus | None
) -> None:
    group = _group(state) if state is not None else None
    monkeypatch.setattr(
        public_upload,
        "ClientGroupRepository",
        Mock(return_value=Mock(get_by_token=AsyncMock(return_value=group))),
    )
    decoder = AsyncMock()
    monkeypatch.setattr(public_upload, "_validated_upload_file", decoder)
    monkeypatch.setattr(public_upload, "upload_session_matches_identifier", lambda *_: True)
    file = UploadFile(filename="untrusted.heic", file=io.BytesIO(b"not-decoded"))
    with pytest.raises(HTTPException) as exc:
        await public_upload.upload_passport(
            token="synthetic-link",
            background_tasks=BackgroundTasks(),
            client_name="Traveller",
            acquisition_mode="file",
            upload_idempotency_key="a" * 40,
            upload_session_id="a" * 40,
            qualifier_selection_token=None,
            file=file,
            passport_back_file=file,
            passport_photo_file=None,
            use_case=Mock(),
            session=AsyncMock(),
        )
    assert exc.value.status_code == 404
    decoder.assert_not_awaited()
    assert file.file.tell() == 0


def test_soft_deleted_active_group_is_also_revoked() -> None:
    from app.application.security.public_upload_capability import public_upload_is_active

    group = _group(GroupStatus.ACTIVE)
    group.deleted_at = datetime.now(tz=UTC)
    assert not public_upload_is_active(group)
