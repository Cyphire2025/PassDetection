"""Real SQL policy, encrypted credentials and delegated dashboard boundaries."""

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.application.assistant.contracts import AssistantError
from app.application.assistant.settings_contracts import (
    AssistantConfiguration,
    AssistantSettingsUpdate,
)
from app.core.assistant_config import AssistantSettings
from app.domain.entities.entities import UserRole
from app.infrastructure.assistant import settings_store
from app.infrastructure.assistant.settings_store import (
    SETTINGS_KEY,
    AssistantSnapshot,
    load_snapshot,
    provider_key,
    runtime_settings,
    save_settings,
)
from app.infrastructure.assistant.store import account_scope, assistant_store
from app.infrastructure.database.models import AuditLogModel, PlatformSettingModel, UserModel
from app.presentation.api.v1.routes.ai_assistant_settings import _response
from app.presentation.assistant import reads
from tests.integration.test_assistant_read_only import workspace as workspace


@pytest.fixture(autouse=True)
def dedicated_credentials_only(monkeypatch):
    monkeypatch.setattr(
        settings_store,
        "get_assistant_settings",
        lambda: AssistantSettings(openai_api_key="", gemini_api_key="", _env_file=None),
    )


async def test_saved_key_is_encrypted_hidden_and_preserved_with_optimistic_revision(workspace):
    session, actor, _, _, _, _, _ = workspace
    secret = "synthetic-gemini-secret-123456"
    first = await save_settings(
        session,
        actor,
        AssistantSettingsUpdate(
            expected_revision=0, configuration=AssistantConfiguration(), gemini_api_key=secret
        ),
    )
    row = await session.scalar(
        select(PlatformSettingModel).where(PlatformSettingModel.key == SETTINGS_KEY)
    )
    assert secret not in json.dumps(row.value)
    assert first.revision == 1 and provider_key(first, "gemini").get_secret_value() == secret
    public = await _response(session, first)
    assert public.credentials == {"gemini": True, "openai": False}
    assert secret not in public.model_dump_json() and "v1:" not in public.model_dump_json()
    second = await save_settings(
        session,
        actor,
        AssistantSettingsUpdate(
            expected_revision=1, configuration=AssistantConfiguration(enabled=False)
        ),
    )
    assert not second.allows(actor)
    assert provider_key(second, "gemini").get_secret_value() == secret
    assert (await runtime_settings(session)).revision == 2
    with pytest.raises(AssistantError, match="Reload") as conflict:
        await save_settings(
            session,
            actor,
            AssistantSettingsUpdate(expected_revision=1, configuration=AssistantConfiguration()),
        )
    assert conflict.value.status == 409
    audit = (await session.scalars(select(AuditLogModel))).all()
    assert len(audit) == 2 and secret not in str([item.__dict__ for item in audit])


async def test_clear_overrides_environment_key_and_does_not_touch_other_provider(
    workspace, monkeypatch
):
    session, actor, _, _, _, _, _ = workspace
    monkeypatch.setattr(
        settings_store,
        "get_assistant_settings",
        lambda: AssistantSettings(
            openai_api_key="synthetic-environment-openai",
            gemini_api_key="synthetic-environment-gemini",
            _env_file=None,
        ),
    )
    snapshot = await save_settings(
        session,
        actor,
        AssistantSettingsUpdate(
            expected_revision=0, configuration=AssistantConfiguration(), clear_gemini_key=True
        ),
    )
    assert provider_key(snapshot, "gemini").get_secret_value() == ""
    assert provider_key(snapshot, "openai").get_secret_value() == "synthetic-environment-openai"
    assert not (await runtime_settings(session)).configured


async def test_default_superadmin_only_roles_individual_and_off_switch(workspace):
    _, actor, agency, _, _, _, _ = workspace
    manager = replace(actor, id=uuid4(), role=UserRole.AGENCY_MANAGER, agency_id=agency.id)
    assert AssistantSnapshot().allows(actor) and not AssistantSnapshot().allows(manager)
    granted = AssistantSnapshot(
        configuration=AssistantConfiguration(allowed_roles=["agency_manager"])
    )
    assert granted.allows(manager)
    assert not granted.allows(replace(manager, is_active=False))
    assert not granted.allows(replace(manager, agency_id=None))
    assert not granted.allows(replace(manager, role=UserRole.AGENCY_STAFF))
    personal = AssistantSnapshot(
        configuration=AssistantConfiguration(allowed_user_ids=[manager.id])
    )
    assert personal.allows(manager)
    assert not personal.allows(replace(manager, role=UserRole.CLIENT_MANAGER))
    assert not AssistantSnapshot(configuration=AssistantConfiguration(enabled=False)).allows(actor)


async def test_grant_must_reference_active_office_account_and_settings_require_superadmin(
    workspace,
):
    session, actor, agency, _, _, _, _ = workspace
    with pytest.raises(AssistantError) as denied:
        await save_settings(
            session,
            replace(actor, role=UserRole.AGENCY_ADMIN, agency_id=agency.id),
            AssistantSettingsUpdate(expected_revision=0, configuration=AssistantConfiguration()),
        )
    assert denied.value.status == 403
    with pytest.raises(AssistantError) as invalid:
        await save_settings(
            session,
            actor,
            AssistantSettingsUpdate(
                expected_revision=0,
                configuration=AssistantConfiguration(allowed_user_ids=[uuid4()]),
            ),
        )
    assert invalid.value.code == "invalid_grant"
    assert (await load_snapshot(session)).revision == 0


async def test_delegated_reader_rechecks_policy_and_enforces_agency_and_view_scope(workspace):
    session, actor, agency, other, group, request, _ = workspace
    await save_settings(
        session,
        actor,
        AssistantSettingsUpdate(
            expected_revision=0,
            configuration=AssistantConfiguration(allowed_roles=["agency_admin"]),
        ),
    )
    await session.execute(
        update(UserModel)
        .where(UserModel.id == actor.id)
        .values(role="agency_admin", agency_id=agency.id)
    )
    await session.commit()
    delegated = replace(actor, role=UserRole.AGENCY_ADMIN, agency_id=agency.id)
    reader = reads.DashboardReader(request, delegated)
    overview = await reader.overview()
    assert [item["id"] for item in overview["agencies"]] == [str(agency.id)]
    result = await reader.read("group_details", {"group_id": str(group.id)})
    assert "Synthetic departure" in json.dumps(result)
    with pytest.raises(AssistantError) as mismatch:
        await reader.read("group_details", {"group_id": str(group.id)}, agency_id=str(other.id))
    assert mismatch.value.status == 403
    with pytest.raises(AssistantError) as forbidden:
        await reader.read("platform_settings", {})
    assert forbidden.value.code in {"view_denied", "unknown_view"}
    catalog = json.dumps(reads.data_catalog(actor=delegated))
    assert "platform_settings" not in catalog
    # Revoking a grant blocks the same actor and reader, without a new login.
    await session.execute(
        update(PlatformSettingModel)
        .where(PlatformSettingModel.key == SETTINGS_KEY)
        .values(
            value={
                "revision": 2,
                "configuration": AssistantConfiguration().model_dump(mode="json"),
                "encrypted_keys": {},
            }
        )
    )
    await session.commit()
    with pytest.raises(AssistantError) as revoked:
        await reader.overview()
    assert revoked.value.status == 403


async def test_staff_requires_group_assignment_after_receiving_ai_access(workspace):
    from app.domain.exceptions.exceptions import AuthorizationError
    from app.infrastructure.database.models import ManagerGroupAccessModel

    session, actor, agency, _, group, request, _ = workspace
    await save_settings(
        session,
        actor,
        AssistantSettingsUpdate(
            expected_revision=0,
            configuration=AssistantConfiguration(allowed_roles=["agency_staff"]),
        ),
    )
    await session.execute(
        update(UserModel)
        .where(UserModel.id == actor.id)
        .values(role="agency_staff", agency_id=agency.id)
    )
    await session.commit()
    staff = replace(actor, role=UserRole.AGENCY_STAFF, agency_id=agency.id)
    reader = reads.DashboardReader(request, staff)
    with pytest.raises(AuthorizationError):
        await reader.read("group_details", {"group_id": str(group.id)})
    session.add(
        ManagerGroupAccessModel(
            id=uuid4(), manager_id=actor.id, group_id=group.id, agency_id=agency.id
        )
    )
    await session.commit()
    assert "Synthetic departure" in json.dumps(
        await reader.read("group_details", {"group_id": str(group.id)})
    )


def test_history_is_partitioned_when_role_or_agency_is_reduced(monkeypatch):
    from types import SimpleNamespace

    from app.domain.entities.entities import User
    from app.infrastructure.assistant import store
    from tests.unit.infrastructure.test_assistant_boundaries import MemoryS3

    actor = User.create("scope@example.test", "fixture", "Scope", UserRole.SUPER_ADMIN)
    monkeypatch.setattr(
        store,
        "MinioStorageRepository",
        lambda: SimpleNamespace(
            _client=MemoryS3(), settings=SimpleNamespace(bucket_name="fixture")
        ),
    )
    original = assistant_store(actor)
    reduced = replace(actor, role=UserRole.AGENCY_MANAGER, agency_id=uuid4())
    scoped = assistant_store(reduced)
    assert account_scope(actor) != account_scope(reduced)
    assert original.prefix != scoped.prefix and "/scopes/" in scoped.prefix
