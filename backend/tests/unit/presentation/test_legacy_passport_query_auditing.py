"""Legacy list responses preserve scoped results and audit only successful reads."""

import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.application.dtos.passport_dtos import passport_submission_output_from_entity
from app.domain.entities.entities import PassportSubmission, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.presentation.api.v1.routes.passport_routes import queries


def actor(*, agency=True, role=UserRole.AGENCY_STAFF):
    return User(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4() if agency else None,
        full_name="Synthetic reader",
        email="reader@example.test",
        hashed_password="unused",
        role=role,
    )


@pytest.mark.parametrize("grouped", [False, True])
async def test_legacy_lists_keep_page_content_and_scope_without_auditing_passport_content(
    monkeypatch,
    grouped,
):
    user, group = actor(), uuid.uuid4()
    passenger = PassportSubmission.create(
        group_id=group,
        agency_id=user.agency_id,
        client_name="Private traveller name",
        client_email=None,
        image_s3_key="private/source.jpg",
    )
    dto = passport_submission_output_from_entity(passenger)
    use_case = Mock(execute=AsyncMock(return_value=[dto]))
    audit = AsyncMock()
    monkeypatch.setattr(queries, "record_sensitive_read", audit)
    crops = Mock(list_for_submissions=AsyncMock(return_value={}))
    monkeypatch.setattr(queries, "PassportImageCropRepository", Mock(return_value=crops))
    arguments = dict(
        current_user=user,
        session=Mock(),
        use_case=use_case,
        skip=25,
        limit=25,
        search="literal%_text",
    )
    if grouped:
        response = await queries.list_passports_by_group(group_id=group, **arguments)
    else:
        response = await queries.list_passports(status_filter="submitted", **arguments)
    assert len(response) == 1 and response[0].id == passenger.id
    assert response[0].group_id == group
    forwarded = use_case.execute.call_args.kwargs
    assert forwarded["agency_id"] == user.agency_id
    assert forwarded["visible_to_user"] is user
    assert forwarded["created_by_user_id"] == user.id
    assert (forwarded["skip"], forwarded["limit"], forwarded["search"]) == (
        25,
        25,
        "literal%_text",
    )
    event = audit.call_args.kwargs
    assert event["agency_id"] == user.agency_id and event["count"] == 1
    assert event["kind"] == ("group_list" if grouped else "list")
    assert event.get("entity_id") == (group if grouped else None)
    assert not {"search", "client_name", "passport_number", "image_s3_key"} & event.keys()


@pytest.mark.parametrize("grouped", [False, True])
async def test_authorization_failure_returns_no_list_and_creates_no_successful_read_event(
    monkeypatch,
    grouped,
):
    user, group = actor(), uuid.uuid4()
    use_case = Mock(execute=AsyncMock(side_effect=AuthorizationError("Denied")))
    audit = AsyncMock()
    monkeypatch.setattr(queries, "record_sensitive_read", audit)
    arguments = dict(current_user=user, session=Mock(), use_case=use_case, search=None)
    with pytest.raises(AuthorizationError):
        if grouped:
            await queries.list_passports_by_group(group_id=group, **arguments)
        else:
            await queries.list_passports(**arguments)
    audit.assert_not_awaited()


async def test_unscoped_identity_and_retained_data_denial_cannot_query_or_audit(monkeypatch):
    use_case, audit = Mock(execute=AsyncMock()), AsyncMock()
    monkeypatch.setattr(queries, "record_sensitive_read", audit)
    user = actor(agency=False)
    arguments = dict(current_user=user, session=Mock(), use_case=use_case, search=None)
    assert await queries.list_passports(**arguments) == []
    assert await queries.list_passports_by_group(group_id=uuid.uuid4(), **arguments) == []
    assert await queries.list_passport_groups(current_user=user, use_case=use_case) == []
    with pytest.raises(HTTPException) as failure:
        await queries.list_passports_by_group(
            group_id=uuid.uuid4(),
            current_user=actor(),
            session=Mock(),
            use_case=use_case,
            search=None,
            include_deleted=True,
        )
    assert failure.value.status_code == 403
    use_case.execute.assert_not_awaited()
    audit.assert_not_awaited()
