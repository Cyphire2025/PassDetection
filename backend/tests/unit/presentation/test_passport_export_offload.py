from __future__ import annotations

import threading
import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from app.domain.entities.entities import PassportSubmission, User, UserRole
from app.presentation.api.v1.routes.passport_routes import selected_exports
from app.presentation.api.v1.schemas.passport_schemas import ExportSelectedPassportsRequest


@pytest.mark.parametrize("ecr_enabled", [False, True])
async def test_selected_export_runs_workbook_generation_outside_request_thread(
    monkeypatch: pytest.MonkeyPatch, ecr_enabled: bool,
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
    group_details = {submission.group_id: {"passport_ecr_enabled": ecr_enabled}}
    monkeypatch.setattr(selected_exports, "_export_group_details", AsyncMock(return_value=group_details))
    from app.infrastructure.ecr import passport_runtime

    verdicts = {submission.id: "ECR"}
    lookup = AsyncMock(return_value=verdicts)
    monkeypatch.setattr(passport_runtime, "passport_ecr_results", lookup)
    worker_threads: list[int] = []

    def export(*_args, **_kwargs):
        assert _kwargs["ecr_results"] == (verdicts if ecr_enabled else {})
        assert _kwargs["group_details"] == group_details
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
    if ecr_enabled:
        lookup.assert_awaited_once_with(
            session, [submission.id], agency_id=submission.agency_id,
            expected_source_keys={submission.id: submission.passport_back_s3_key},
        )
    else:
        lookup.assert_not_awaited()
