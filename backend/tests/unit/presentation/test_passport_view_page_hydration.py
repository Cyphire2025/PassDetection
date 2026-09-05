from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.application.dtos.passport_dtos import passport_submission_output_from_entity
from app.domain.entities.entities import PassportSubmission, User, UserRole
from app.infrastructure.repositories.passport_submission_view_repository import (
    PassportSubmissionViewRepository,
    PassportViewProjection,
)
from app.presentation.api.v1.routes.passport_routes import queries


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        full_name="Test Staff",
        email="synthetic@example.test",
        hashed_password="unused",
        role=UserRole.AGENCY_STAFF,
    )


async def test_projection_omits_raw_documents_and_page_query_retains_staff_scope() -> None:
    result = Mock()
    result.mappings.return_value = []
    result.scalars.return_value = []
    session = Mock(execute=AsyncMock(return_value=result))
    repository = PassportSubmissionViewRepository(session)
    user, group_id = _user(), uuid.uuid4()
    await repository.projection(group_id=group_id, user=user, include_deleted=False)
    statement = session.execute.call_args.args[0]
    selected = {column.key for column in statement.selected_columns}
    assert selected == set(PassportViewProjection.__dataclass_fields__)
    assert not selected & {
        "image_s3_key",
        "mrz_raw",
        "staff_metadata",
        "confidence_score",
        "extraction_conflicts",
    }
    assert "manager_group_access" in str(statement)
    ids = [uuid.uuid4(), uuid.uuid4()]
    await repository.page_details(submission_ids=ids, group_id=group_id, user=user)
    query = session.execute.call_args.args[0]
    assert ids in query.compile().params.values()
    assert user.agency_id in query.compile().params.values()
    assert "manager_group_access" in str(query)
    assert "client_groups.deleted_at IS NULL" in str(query)
    assert "passport_submissions.status IN" in str(query)


@pytest.mark.parametrize("changed_revision", [False, True, "review_updated"])
async def test_filtered_page_hydrates_only_visible_rows_and_rejects_revision_race(
    monkeypatch: pytest.MonkeyPatch, changed_revision: bool | str
) -> None:
    user, group_id = _user(), uuid.uuid4()
    projections = []
    details = {}
    for index in range(120):
        passenger = PassportSubmission.create(
            group_id=group_id,
            agency_id=user.agency_id,
            client_name=f"Traveller {index:03}",
            client_email=None,
            image_s3_key="synthetic/front.jpg",
        )
        dto = replace(passport_submission_output_from_entity(passenger), status="submitted")
        projections.append(
            PassportViewProjection(
                **{key: getattr(dto, key) for key in PassportViewProjection.__dataclass_fields__}
            )
        )
        details[dto.id] = dto

    async def page_details(**kwargs):
        selected = kwargs["submission_ids"]
        assert selected == [row.id for row in projections[50:100]]
        if changed_revision == "review_updated":
            return {
                key: replace(
                    details[key], updated_at=details[key].updated_at + timedelta(seconds=1)
                )
                for key in selected
            }
        return {
            key: replace(details[key], extraction_revision=1) if changed_revision else details[key]
            for key in selected
        }

    repository = Mock(
        projection=AsyncMock(return_value=projections),
        page_details=AsyncMock(side_effect=page_details),
    )
    monkeypatch.setattr(queries, "PassportSubmissionViewRepository", Mock(return_value=repository))
    monkeypatch.setattr(
        queries,
        "PassportImageCropRepository",
        Mock(return_value=Mock(list_for_submissions=AsyncMock(return_value={}))),
    )
    result = Mock()
    result.scalar_one_or_none.return_value = None
    session = Mock(execute=AsyncMock(return_value=result))
    kwargs = dict(
        group_id=group_id,
        submission_filter="all",
        sort_by="name",
        sort_order="asc",
        page=2,
        page_size=50,
        search=None,
        include_deleted=False,
        current_user=user,
        session=session,
    )
    if changed_revision:
        with pytest.raises(HTTPException) as error:
            await queries.list_passports_by_group_view(**kwargs)
        assert error.value.status_code == 409
    else:
        response = await queries.list_passports_by_group_view(**kwargs)
        assert response.total == 120
        assert response.returned_count == 50
        assert [row.id for row in response.items] == [row.id for row in projections[50:100]]
        assert len(response.ordered_selection_snapshot) == 120
