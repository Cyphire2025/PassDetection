"""Settings authorization, MFA, CSRF and write-only responses over the real API."""

from dataclasses import replace

from app.application.assistant.settings_contracts import AssistantConfiguration
from app.domain.entities.entities import UserRole
from app.presentation.dependencies.auth import get_current_active_user, require_recent_mfa
from tests.integration.test_assistant_read_only import workspace as workspace


async def test_settings_authorization_and_key_writes_require_mfa_and_csrf(client, workspace):
    _, actor, agency, _, _, _, _ = workspace
    app = client._transport.app
    app.dependency_overrides[get_current_active_user] = lambda: actor
    first = await client.get("/api/v1/ai-assistant/settings")
    assert first.status_code == 200 and first.json()["credentials"]["gemini"] is False
    body = {
        "expected_revision": 0,
        "configuration": AssistantConfiguration().model_dump(mode="json"),
        "gemini_api_key": "synthetic-http-gemini-secret",
    }
    step_up = await client.put("/api/v1/ai-assistant/settings", json=body)
    assert step_up.status_code == 403 and "STEP_UP_REQUIRED" in step_up.text
    app.dependency_overrides[require_recent_mfa] = lambda: actor
    client.cookies.set("access_token", "synthetic-cookie")
    rejected = await client.put(
        "/api/v1/ai-assistant/settings",
        json=body,
        headers={"Origin": "https://attacker.example.test"},
    )
    assert rejected.status_code == 403
    client.cookies.clear()
    saved = await client.put("/api/v1/ai-assistant/settings", json=body)
    assert saved.status_code == 200 and saved.json()["credentials"]["gemini"] is True
    assert body["gemini_api_key"] not in saved.text
    assert body["gemini_api_key"] not in (await client.get("/api/v1/ai-assistant/settings")).text
    app.dependency_overrides[get_current_active_user] = lambda: replace(
        actor, role=UserRole.AGENCY_ADMIN, agency_id=agency.id
    )
    for path in ("/settings", "/settings/people"):
        assert (await client.get("/api/v1/ai-assistant" + path)).status_code == 403
    assert (await client.put("/api/v1/ai-assistant/settings", json=body)).status_code == 403
