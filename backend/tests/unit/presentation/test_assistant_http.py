"""Assistant-specific authorization, CSRF, pending setup and safe upload failures."""

import io
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from pypdf import PdfWriter

from app.application.assistant.contracts import AssistantError
from app.core.assistant_config import AssistantSettings
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.infrastructure.assistant import attachments
from app.infrastructure.assistant.settings_store import AssistantSnapshot
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.upload_security import UploadSecurityContext, UploadSecurityService
from app.infrastructure.security.upload_validator import MalwareScannerUnavailableError
from app.presentation.api.v1.routes import ai_assistant
from app.presentation.dependencies.auth import get_current_active_user


async def test_status_is_private_admin_only_and_chat_requires_configuration(monkeypatch):
    app = FastAPI()
    app.include_router(ai_assistant.router, prefix="/api/v1/ai-assistant")
    actor = User.create(
        "assistant@example.test", "fixture-hash", "Assistant test", UserRole.SUPER_ADMIN
    )
    app.dependency_overrides[get_current_active_user] = lambda: actor
    session = SimpleNamespace(rollback=AsyncMock())
    app.dependency_overrides[get_db_session] = lambda: session
    monkeypatch.setattr(ai_assistant, "load_snapshot", AsyncMock(return_value=AssistantSnapshot()))
    app.dependency_overrides[ai_assistant.assistant_runtime] = lambda: AssistantSettings(
        openai_api_key="", _env_file=None
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/ai-assistant/status")
        assert response.status_code == 200
        assert (
            response.json()["configured"] is False and response.json()["reasoning_effort"] == "high"
        )
        assert response.headers["cache-control"] == "private, no-store"
        app.dependency_overrides[get_current_active_user] = lambda: replace(
            actor, role=UserRole.AGENCY_ADMIN
        )
        assert (await client.get("/api/v1/ai-assistant/status")).status_code == 403
        app.dependency_overrides[get_current_active_user] = lambda: actor
        body = {
            "request_id": str(uuid4()),
            "conversation_id": str(uuid4()),
            "text": "Current group overview",
        }
        pending = await client.post("/api/v1/ai-assistant/chat", json=body)
        assert pending.status_code == 503 and pending.json()["detail"]["code"] == "setup_pending"
        client.cookies.set(get_settings().jwt.access_cookie_name, "synthetic-cookie")
        cross_site = await client.post(
            "/api/v1/ai-assistant/chat",
            json=body,
            headers={"Origin": "https://attacker.example.test"},
        )
        assert cross_site.status_code == 403


@pytest.mark.parametrize("kind", ["image", "pdf", "text"])
async def test_valid_formats_pass_the_existing_scanner_before_model_input(
    monkeypatch, test_settings, kind
):
    security = UploadSecurityService(settings=test_settings)
    security._record = AsyncMock()
    security._scanner = SimpleNamespace(scan=lambda _: None)
    monkeypatch.setattr(attachments, "UploadSecurityService", lambda: security)
    context = UploadSecurityContext(
        ingestion_flow="assistant_fixture", user_id=uuid4(), agency_id=None
    )
    if kind == "image":
        output = io.BytesIO()
        Image.new("RGB", (40, 40), "beige").save(output, format="PNG")
        content, name, mime = output.getvalue(), "sample.png", "image/png"
    elif kind == "pdf":
        output = io.BytesIO()
        pdf = PdfWriter()
        pdf.add_blank_page(width=100, height=100)
        pdf.write(output)
        content, name, mime = output.getvalue(), "sample.pdf", "application/pdf"
    else:
        content, name, mime = b"Synthetic itinerary", "plan.txt", "text/plain"
    _, _, actual_mime, text = await attachments.prepare_attachment(content, name, mime, context)
    assert actual_mime.startswith("image/") if kind == "image" else actual_mime == mime
    if kind == "text":
        assert text == "Synthetic itinerary"
    assert security._record.await_count >= 1


async def test_scanner_unavailability_is_retryable_and_does_not_become_file_rejection(monkeypatch):
    security = SimpleNamespace(
        _scan_original=AsyncMock(side_effect=MalwareScannerUnavailableError("fixture"))
    )
    monkeypatch.setattr(attachments, "UploadSecurityService", lambda: security)
    with pytest.raises(AssistantError) as exc:
        await attachments.prepare_attachment(
            b"Synthetic itinerary",
            "plan.txt",
            "text/plain",
            UploadSecurityContext(
                ingestion_flow="assistant_fixture", user_id=uuid4(), agency_id=None
            ),
        )
    assert exc.value.status == 503 and exc.value.code == "scanner_unavailable"


async def test_unicode_excerpts_fit_private_record_limits_without_losing_original_file(monkeypatch):
    security = SimpleNamespace(_scan_original=AsyncMock(), _record=AsyncMock())
    monkeypatch.setattr(attachments, "UploadSecurityService", lambda: security)
    original = ("🧳" * 60000).encode()
    content, _, _, text = await attachments.prepare_attachment(
        original,
        "notes.txt",
        "text/plain",
        UploadSecurityContext(ingestion_flow="assistant_fixture", user_id=uuid4(), agency_id=None),
    )
    assert content == original
    assert len(text.encode()) <= 128 * 1024
