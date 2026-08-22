from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.application.dtos.client_group_dtos import CreateClientGroupInputDTO
from app.application.platform_policies import (
    PlatformPolicies,
    PlatformPolicyConfigurationError,
)
from app.application.use_cases.client_groups.create_client_group_use_case import (
    CreateClientGroupUseCase,
)


def test_platform_policy_defaults_are_complete_and_conservative() -> None:
    policy = PlatformPolicies.from_mapping(None)

    assert policy.default_group_status == "active"
    assert policy.duplicate_contact_policy == "block_same_group"
    assert policy.auto_archive_closed_groups_days == 90
    assert policy.passport_data_retention_days == 365
    assert policy.audit_log_retention_days == 365
    assert PlatformPolicies.from_mapping(policy.as_dict()) == policy


@pytest.mark.parametrize(
    "override",
    [
        {"require_client_email": "true"},
        {"duplicate_contact_policy": "unknown"},
        {"default_group_status": "archived"},
        {"passport_data_retention_days": 0},
        {"audit_log_retention_days": True},
        {"mrz_review_threshold": 1.1},
    ],
)
def test_platform_policy_loader_rejects_corrupt_persisted_values(
    override: dict[str, object],
) -> None:
    with pytest.raises(PlatformPolicyConfigurationError):
        PlatformPolicies.from_mapping(override)


@pytest.mark.asyncio
async def test_default_group_status_is_applied_at_the_domain_creation_boundary() -> None:
    group_repository = AsyncMock()
    provider = AsyncMock()
    provider.load.return_value = PlatformPolicies(
        default_group_status="closed",
        passport_data_retention_days=30,
    )
    use_case = CreateClientGroupUseCase(group_repository, provider)

    result = await use_case.execute(
        dto=CreateClientGroupInputDTO(name="Policy Group"),
        agency_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
    )

    saved_group = group_repository.save.await_args.args[0]
    assert result.status == "closed"
    assert saved_group.closed_at is not None
    assert saved_group.passport_retention_days_applied == 30
    assert saved_group.passport_purge_at is not None
    assert (saved_group.passport_purge_at - saved_group.closed_at).days == 30
