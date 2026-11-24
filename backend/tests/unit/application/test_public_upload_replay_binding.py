"""Recovery credentials remain bound to one qualifier across concurrent replay gates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.application.mobile.group_capacity import GroupPassengerCapacityGuard
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.domain.entities.entities import ClientGroup, PassportSubmission, QualifierSelection
from app.domain.exceptions.exceptions import ValidationError
from app.domain.value_objects.qualifier_relations import hash_qualifier_selection_token


def upload_fixture():
    group = ClientGroup.create(
        name="Synthetic replay boundary",
        token="synthetic-public-replay-link",
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        relation_with_qualifier_enabled=True,
    )
    selection_token = "s" * 43
    now = datetime.now(tz=UTC)
    selection = QualifierSelection.create(
        group_id=group.id,
        token_hash=hash_qualifier_selection_token(selection_token),
        is_self=False,
        relation_code="spouse",
        selected_at=now,
        expires_at=now + timedelta(hours=1),
    )
    groups, passports, storage, selections = [AsyncMock() for _ in range(4)]
    capacity = AsyncMock(spec=GroupPassengerCapacityGuard)
    groups.get_by_token.return_value = group
    selections.get_by_token_hash.return_value = selection
    selections.get_submission_id.return_value = None
    use_case = SubmitPassportUseCase(
        groups,
        passports,
        storage,
        qualifier_selection_repo=selections,
        group_capacity_guard=capacity,
    )
    request = dict(
        token=group.token,
        file_content=b"synthetic front",
        content_type="image/jpeg",
        filename="synthetic-front.jpg",
        client_name="Synthetic passenger",
        passport_back=(b"synthetic back", "image/jpeg", "synthetic-back.jpg"),
        upload_idempotency_key="r" * 43,
        qualifier_selection_token=selection_token,
    )
    return use_case, group, selection, passports, storage, selections, capacity, request


@pytest.mark.parametrize("gate", ["initial", "capacity", "save"])
@pytest.mark.parametrize("matches", [True, False])
async def test_actual_upload_replay_preserves_or_rejects_the_qualifier_binding(gate, matches):
    use_case, group, selection, passports, storage, selections, capacity, request = upload_fixture()
    existing = PassportSubmission.create(
        group_id=group.id,
        agency_id=group.agency_id,
        client_name="Existing synthetic passenger",
        client_email=None,
        image_s3_key="synthetic/retained/front.jpg",
        upload_idempotency_key=request["upload_idempotency_key"],
    )
    existing.qualifier_selection_id = selection.id if matches else uuid.uuid4()
    lookups = {"initial": [existing], "capacity": [None, existing], "save": [None, None]}
    passports.get_by_upload_idempotency_key.side_effect = lookups[gate]
    passports.save_idempotent.return_value = existing, False

    if matches:
        result = await use_case.execute(**request)
        assert result.id == existing.id
    else:
        with pytest.raises(ValidationError) as error:
            await use_case.execute(**request)
        assert error.value.field == "qualifier_selection_token"

    selections.get_by_token_hash.assert_awaited_once_with(
        group.id,
        hash_qualifier_selection_token(request["qualifier_selection_token"]),
        for_update=True,
    )
    passports.update.assert_not_awaited()
    if gate == "initial":
        storage.upload_file.assert_not_awaited()
        storage.delete_files.assert_not_awaited()
        capacity.lock_group.assert_not_awaited()
    else:
        assert storage.upload_file.await_count == 2
        keys = [call.kwargs["file_name"] for call in storage.upload_file.await_args_list]
        assert len(set(keys)) == 2
        assert all(key.startswith(f"drafts/{group.agency_id}/{group.id}/") for key in keys)
        storage.delete_files.assert_awaited_once_with(keys)
        capacity.lock_group.assert_awaited_once_with(agency_id=group.agency_id, group_id=group.id)
    if gate == "save":
        passports.save_idempotent.assert_awaited_once()
        capacity.assert_available.assert_awaited_once_with(
            agency_id=group.agency_id,
            group_id=group.id,
            additional_passengers=1,
        )
    else:
        passports.save_idempotent.assert_not_awaited()
        capacity.assert_available.assert_not_awaited()


@pytest.mark.parametrize("credential", ["short", "r" * 129, "!" * 43])
async def test_invalid_recovery_credential_stops_before_selection_storage_or_capacity(credential):
    use_case, _group, _selection, passports, storage, selections, capacity, request = (
        upload_fixture()
    )
    request["upload_idempotency_key"] = credential
    with pytest.raises(ValidationError) as error:
        await use_case.execute(**request)
    assert error.value.field == "upload_idempotency_key"
    passports.get_by_upload_idempotency_key.assert_not_awaited()
    selections.get_by_token_hash.assert_not_awaited()
    storage.upload_file.assert_not_awaited()
    capacity.lock_group.assert_not_awaited()
