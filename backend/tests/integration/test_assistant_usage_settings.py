"""Persisted policy, immediate runtime use and private usage visibility."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.application.assistant.settings_contracts import (
    AssistantConfiguration,
    AssistantSettingsUpdate,
)
from app.application.assistant.usage_contracts import AssistantUsageResponse
from app.core.assistant_usage import AssistantUsageLimits
from app.domain.entities.entities import UserRole
from app.infrastructure.assistant.settings_store import (
    SETTINGS_KEY,
    load_snapshot,
    runtime_settings,
    save_settings,
)
from app.infrastructure.database.models import PlatformSettingModel
from app.presentation.api.v1.routes import ai_assistant_settings
from app.presentation.dependencies.auth import get_current_active_user
from tests.integration.test_assistant_read_only import workspace as workspace


async def test_limits_persist_with_revision_and_take_effect_without_restarting(workspace):
    session, actor, _, _, _, _, _ = workspace
    requested = AssistantUsageLimits(
        daily_voice_chats=90,
        voice_connection_minutes=35,
        daily_requests=450,
        daily_images=26,
        daily_uploads=100,
        daily_speech_requests=500,
    )
    first = await save_settings(
        session,
        actor,
        AssistantSettingsUpdate(
            expected_revision=0, configuration=AssistantConfiguration(usage_limits=requested)
        ),
    )
    assert first.configuration.usage_limits == requested
    reloaded = await load_snapshot(session)
    assert reloaded.revision == 1 and reloaded.configuration.usage_limits == requested
    runtime = await runtime_settings(session)
    assert (
        runtime.daily_requests == 450
        and runtime.daily_images == 26
        and runtime.usage_limits == requested
    )


async def test_existing_settings_without_usage_policy_load_defaults_without_a_migration(workspace):
    session, actor, _, _, _, _, _ = workspace
    await save_settings(
        session,
        actor,
        AssistantSettingsUpdate(
            expected_revision=0, configuration=AssistantConfiguration(gemini_voice="Kore")
        ),
    )
    row = await session.scalar(
        select(PlatformSettingModel).where(PlatformSettingModel.key == SETTINGS_KEY)
    )
    value = dict(row.value)
    value["configuration"] = dict(value["configuration"])
    value["configuration"].pop("usage_limits")
    row.value = value
    await session.commit()
    snapshot = await load_snapshot(session)
    assert snapshot.configuration.gemini_voice == "Kore"
    assert snapshot.configuration.usage_limits == AssistantUsageLimits()


@pytest.mark.parametrize(
    "field,value",
    [
        ("daily_voice_chats", -1),
        ("voice_connection_minutes", 0),
        ("voice_connection_minutes", 61),
        ("daily_requests", 10001),
        ("daily_images", 501),
        ("daily_uploads", 2001),
        ("daily_speech_requests", 10001),
    ],
)
def test_usage_limit_boundaries_are_validated(field, value):
    with pytest.raises(ValidationError):
        AssistantUsageLimits(**{field: value})


async def test_usage_is_superadmin_only_and_no_store(client, workspace, monkeypatch):
    _, actor, agency, _, _, _, _ = workspace
    agency_id = agency.id
    app = client._transport.app
    app.dependency_overrides[get_current_active_user] = lambda: actor
    now = datetime.now(UTC)
    result = AssistantUsageResponse(
        observed_at=now,
        resets_at=now + timedelta(hours=1),
        limits=AssistantUsageLimits(),
        used={"voice_chats": 2},
    )
    read = AsyncMock(return_value=result)
    monkeypatch.setattr(ai_assistant_settings, "usage_snapshot", read)
    response = await client.get("/api/v1/ai-assistant/settings/usage")
    assert response.status_code == 200 and response.json()["used"]["voice_chats"] == 2
    assert {"private", "no-store"} <= set(response.headers["cache-control"].split(", "))
    assert read.await_args.args[0] == actor.id
    app.dependency_overrides[get_current_active_user] = lambda: replace(
        actor, role=UserRole.AGENCY_ADMIN, agency_id=agency_id
    )
    assert (await client.get("/api/v1/ai-assistant/settings/usage")).status_code == 403
    assert read.await_count == 1
