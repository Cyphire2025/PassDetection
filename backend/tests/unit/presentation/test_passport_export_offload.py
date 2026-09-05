from __future__ import annotations

import threading
import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from app.domain.entities.entities import PassportSubmission, User, UserRole
from app.presentation.api.v1.routes.passport_routes import selected_exports
from app.presentation.api.v1.schemas.passport_schemas import ExportSelectedPassportsRequest


async def test_selected_export_runs_workbook_generation_outside_request_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_thread = threading.get_ident()
    submission = PassportSubmission.create(
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        client_name="Synthetic traveller",
        client_email=None,
        image_s3_key="synthetic/front.jpg",
    )
    user = User(
        id=uuid.uuid4(),
        agency_id=submission.agency_id,
        email="synthetic@example.test",
        full_name="Synthetic admin",
        hashed_password="unused",
        role=UserRole.AGENCY_ADMIN,
    )
    result = Mock()
    result.scalars.return_value.all.return_value = [submission]
    session = Mock(execute=AsyncMock(return_value=result))
    monkeypatch.setattr(
        selected_exports.PassportSubmissionRepository, "_to_entity", lambda item: item
    )
    monkeypatch.setattr(selected_exports, "_export_whatsapp_match_rows", AsyncMock(return_value={}))
    monkeypatch.setattr(selected_exports, "_export_group_details", AsyncMock(return_value={}))
    worker_threads: list[int] = []

    def export(*_args, **_kwargs):
        worker_threads.append(threading.get_ident())
        return b"synthetic-workbook"

    monkeypatch.setattr(selected_exports.PassportExcelExporter, "export_group", export)
    response = await selected_exports.export_selected_passports(
        ExportSelectedPassportsRequest(submission_ids=[submission.id]),
        user,
        session,
    )
    assert response.status_code == 200
    assert worker_threads and worker_threads[0] != request_thread
