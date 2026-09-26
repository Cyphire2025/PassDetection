from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.application.dtos.passport_dtos import passport_submission_output_from_entity
from app.application.use_cases.passports.submission_view import prepare_submission_view
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


@pytest.mark.parametrize("changed_revision", [False, True, "review_updated", "group_revision"])
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
            key: replace(details[key], extraction_revision=1) if changed_revision is True else details[key]
            for key in selected
        }

    repository = Mock(
        revision=AsyncMock(return_value=(1 if changed_revision == "group_revision" else 0, None)),
        projection=AsyncMock(return_value=projections),
        page_details=AsyncMock(side_effect=page_details),
    )
    monkeypatch.setattr(queries, "PassportSubmissionViewRepository", Mock(return_value=repository))
    index = prepare_submission_view(projections, submission_filter="all", sort_by="name",
                                    sort_order="asc", search=None, page_size=50)
    monkeypatch.setattr(queries, "prepared_roster", AsyncMock(return_value=(index, (0, None))))
    monkeypatch.setattr(queries, "record_sensitive_read", AsyncMock())
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


@pytest.mark.parametrize("count", [3, 303, 603])
async def test_duplicate_payload_is_bounded_and_selection_preserves_all_revisions(
    monkeypatch: pytest.MonkeyPatch, count: int,
) -> None:
    user, group_id = _user(), uuid.uuid4()
    details = {}
    projections = []
    for index in range(count):
        passenger = PassportSubmission.create(
            group_id=group_id, agency_id=user.agency_id, client_name=f"Traveller {index:03}",
            client_email=None, image_s3_key="synthetic/front.jpg",
        )
        dto = replace(
            passport_submission_output_from_entity(passenger), status="submitted",
            extraction_revision=index,
            confirmed_fields={"passport_number": "P123", "place_of_issue": "Chennai"},
        )
        details[dto.id] = dto
        projections.append(PassportViewProjection(
            **{key: getattr(dto, key) for key in PassportViewProjection.__dataclass_fields__}
        ))

    async def page_details(**kwargs):
        assert len(kwargs["submission_ids"]) <= 50
        return {key: details[key] for key in kwargs["submission_ids"]}

    repository = Mock(projection=AsyncMock(return_value=projections),
                      revision=AsyncMock(return_value=(0, None)),
                      page_details=AsyncMock(side_effect=page_details))
    monkeypatch.setattr(queries, "PassportSubmissionViewRepository", Mock(return_value=repository))
    index = prepare_submission_view(projections, submission_filter="duplicates", sort_by="name",
                                    sort_order="asc", search=None, page_size=50)
    monkeypatch.setattr(queries, "prepared_roster", AsyncMock(return_value=(index, (0, None))))
    monkeypatch.setattr(queries, "record_sensitive_read", AsyncMock())
    crops = Mock(list_for_submissions=AsyncMock(return_value={}))
    monkeypatch.setattr(queries, "PassportImageCropRepository", Mock(return_value=crops))
    result = Mock()
    result.scalar_one_or_none.return_value = None
    seen = []
    serialized_sizes = []
    for page in range(1, (count + 49) // 50 + 1):
        response = await queries.list_passports_by_group_view(
            group_id=group_id, submission_filter="duplicates", sort_by="name", sort_order="asc",
            page=page, page_size=50, search=None, include_deleted=False,
            current_user=user, session=Mock(execute=AsyncMock(return_value=result)),
        )
        assert len(crops.list_for_submissions.call_args.args[0]) <= 50
        seen.extend(item.id for item in response.items)
        assert response.total == count
        assert len(response.items) <= 50
        assert {row.submission_id: row.extraction_revision
                for row in response.ordered_selection_snapshot} == {
                    row.id: row.extraction_revision for row in projections
                }
        assert set(response.ordered_submission_ids) == set(details)
        cluster, = response.duplicate_clusters
        assert cluster.visible_member_ids == [item.id for item in response.items]
        for item in response.items:
            assert item.duplicate_cluster_size == count
            assert item.duplicate_cluster_member_ids_complete == (count <= 20)
            assert len(item.duplicate_cluster_member_ids) == (count if count <= 20 else 0)
        serialized_sizes.append(len(response.model_dump_json()))
    assert len(seen) == len(set(seen)) == count
    assert set(seen) == set(details)
    # Full selection metadata is linear in group size, details in page size.
    # This rejects the old 303*303 UUID membership amplification (>3 MB).
    assert max(serialized_sizes) < 250_000
