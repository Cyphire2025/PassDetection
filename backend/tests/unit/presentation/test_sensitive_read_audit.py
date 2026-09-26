from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select

from app.application.use_cases.passports.get_passport_submission_use_case import (
    GetPassportSubmissionUseCase,
)
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.routes import search
from app.presentation.api.v1.routes.passport_routes import covers, image_support, submission_review
from tests.unit.application.test_retained_data_authorization import (
    retained_records as retained_records,
)


async def test_actual_authorized_handlers_record_private_minimal_access(db_session, retained_records, monkeypatch):
    user, records = retained_records
    _, _, _, passport = next(row for row in records if row[:2] == ("owned", "active"))
    monkeypatch.setattr(submission_review, "_response_from_dto", AsyncMock(return_value="detail"))
    monkeypatch.setattr(covers, "MinioStorageRepository", Mock())
    monkeypatch.setattr(covers, "private_object_streaming_response", AsyncMock(return_value="stream"))
    assert await submission_review.get_passport(passport.id, BackgroundTasks(), current_user=user,
        use_case=GetPassportSubmissionUseCase(PassportSubmissionRepository(db_session)), session=db_session) == "detail"
    assert await covers.get_passport_cover(passport.id, "cover", current_user=user, session=db_session) == "stream"
    await image_support._authorized_staff_passport_image(submission_id=passport.id,
        image_type=PassportImageType.PASSPORT_FRONT, current_user=user, session=db_session, require_editor=False)
    results = await search.global_search(q="Needle", limit=30, current_user=user, session=db_session)
    events = list(await db_session.scalars(select(AuditLogModel).where(AuditLogModel.action == "sensitive_read.authorized")))
    assert {row.metadata_json["read_kind"] for row in events} == {"detail", "cover", "image", "search"}
    for event in events:
        assert event.user_id == user.id and event.agency_id == user.agency_id
        assert set(event.metadata_json) == {"read_kind", "authorized_result_count"}
        assert event.actor_email is None and event.ip_address is None
        if event.metadata_json["read_kind"] == "search":
            assert event.entity_id is None
            assert event.metadata_json["authorized_result_count"] == sum(row.type == "passport" for row in results)
        else:
            assert event.entity_id == str(passport.id)


async def test_denied_access_does_not_claim_authorized_read(db_session, retained_records):
    user, records = retained_records
    _, _, _, passport = next(row for row in records if row[:2] == ("owned", "deleted"))
    with pytest.raises(HTTPException):
        await image_support._authorized_staff_passport_image(submission_id=passport.id,
            image_type=PassportImageType.PASSPORT_FRONT, current_user=user, session=db_session, require_editor=False)
    assert list(await db_session.scalars(select(AuditLogModel))) == []


async def test_audit_failure_stops_cover_before_storage(db_session, retained_records, monkeypatch):
    user, records = retained_records
    _, _, _, passport = next(row for row in records if row[:2] == ("owned", "active"))
    monkeypatch.setattr(covers, "record_sensitive_read", AsyncMock(side_effect=RuntimeError("audit unavailable")))
    storage = Mock()
    monkeypatch.setattr(covers, "MinioStorageRepository", storage)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await covers.get_passport_cover(passport.id, "cover", current_user=user, session=db_session)
    storage.assert_not_called()
