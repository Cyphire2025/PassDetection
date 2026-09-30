"""Local HTTP/SDK journey plumbing with synthetic storage, scanner and providers."""

from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app.infrastructure.database.models import AgencyModel
from app.infrastructure.security.contact_spreadsheet_security import (
    XLSX_MEDIA,
    ContactSpreadsheetSecurity,
)
from app.infrastructure.security.upload_security import UploadSecurityService
from app.infrastructure.whatsapp import mcp_publication, template_settings, worker_runtime
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError
from app.presentation.api.v1.routes import whatsapp_send
from tests.integration.test_mcp_artifacts import Evidence, Scanner, Storage, chunks
from tests.integration.test_mcp_authorization import connect
from tests.integration.test_mcp_whatsapp_media import picture
from tests.unit.presentation.test_whatsapp_repeatable_reminders import SQLiteDeliveryClaim


@pytest.fixture
async def excel_message_journey(mcp_fixture, monkeypatch):
    http, session, settings, actor, _security, _dashboard = mcp_fixture
    app = http._transport.app
    agency = AgencyModel(
        id=uuid.uuid4(), name="Synthetic journey agency", email="journey@example.test"
    )
    session.add(agency)
    await session.commit()
    agency_id = str(agency.id)
    settings.whatsapp_access_token = "synthetic-never-sent-token"
    settings.whatsapp_phone_number_id = "synthetic-journey-sender"
    settings.whatsapp_welcome_template_name = "welcome_v1"
    settings.malware_quarantine_enabled = False
    _, tokens = await connect(
        mcp_fixture, scopes=["mcp:read", "mcp:upload", "mcp:change", "mcp:communicate"]
    )
    token = tokens["access_token"]
    storage, scanner, evidence = Storage(), Scanner(), Evidence()
    app.state.mcp_contact_import_storage = app.state.mcp_whatsapp_media_storage = storage
    app.state.mcp_contact_import_security = ContactSpreadsheetSecurity(
        settings=settings,
        scanner=scanner,
        session_factory=lambda: evidence,
        storage=storage,
    )
    app.state.mcp_whatsapp_media_security = UploadSecurityService(
        settings=settings,
        scanner=scanner,
        session_factory=lambda: evidence,
        storage=storage,
    )
    media_provider = AsyncMock(return_value="synthetic-private-header-receipt")
    monkeypatch.setattr(
        "app.application.mcp.whatsapp_media_uploads.upload_whatsapp_image", media_provider
    )

    async def send(**kwargs):
        number = kwargs["to_number"]
        if number.endswith("3212"):
            raise httpx.ReadTimeout("Synthetic response lost after provider handoff")
        if number.endswith("3213"):
            raise WhatsAppCloudApiError("Synthetic definitive rejection", code="FIXTURE_REJECTED")
        return "wamid.synthetic." + number[-4:]

    provider, publication = AsyncMock(side_effect=send), AsyncMock()
    monkeypatch.setattr(worker_runtime, "send_whatsapp_template", provider)
    monkeypatch.setattr(mcp_publication, "publish_whatsapp_task", publication)
    monkeypatch.setattr(whatsapp_send, "pg_insert", SQLiteDeliveryClaim)
    for module in (worker_runtime, mcp_publication, whatsapp_send, template_settings):
        monkeypatch.setattr(module, "get_settings", lambda: settings)

    @asynccontextmanager
    async def sessions():
        yield session

    monkeypatch.setattr(worker_runtime, "AsyncSessionFactory", sessions)
    monkeypatch.setattr(mcp_publication, "AsyncSessionFactory", sessions)

    async def deny_network(*_args, **_kwargs):
        pytest.fail("The journey must never use an external HTTP transport")

    # Actual ASGI transport remains available. A missing provider/storage patch
    # must fail the test before any external network request can be issued.
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", deny_network)
    monkeypatch.setattr(httpx2.AsyncHTTPTransport, "handle_async_request", deny_network)

    @asynccontextmanager
    async def sdk():
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), headers={"Authorization": f"Bearer {token}"}
        ) as client:
            async with Client(
                streamable_http_client("http://localhost:8000/mcp", http_client=client),
                mode="legacy",
            ) as connection:
                yield connection

    async def transfer(path, content, media_type, params, *, key=None):
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": media_type,
            "X-Artifact-Size": str(len(content)),
            "X-Artifact-SHA256": hashlib.sha256(content).hexdigest(),
        }
        if key:
            headers["Idempotency-Key"] = key
        result = await http.post(
            path,
            params={"agency_id": agency_id, **params},
            headers=headers,
            content=chunks(content),
        )
        assert result.status_code == 201, result.text
        return result.json()

    async def upload_workbook(content):
        return await transfer(
            "/mcp/contact-imports/uploads", content, XLSX_MEDIA, {"filename": "journey.xlsx"}
        )

    async def upload_header(broadcast_id):
        return await transfer(
            "/mcp/whatsapp-media/uploads",
            picture(),
            "image/png",
            {"filename": "selected-header.png", "broadcast_id": broadcast_id},
            key="journey-selected-header-001",
        )

    return SimpleNamespace(
        session=session,
        settings=settings,
        actor_id=str(actor.id),
        agency_id=agency_id,
        sdk=sdk,
        upload_workbook=upload_workbook,
        upload_header=upload_header,
        provider=provider,
        media_provider=media_provider,
        publication=publication,
        storage=storage,
        scanner=scanner,
    )


async def tool(sdk, name, arguments):
    result = await sdk.call_tool(name, arguments)
    assert not result.is_error, result.content
    assert result.structured_content is not None
    assert "error" not in result.structured_content, result.structured_content
    return result.structured_content


def broadcast_draft(f, upload_id):
    return {
        "upload_id": upload_id,
        "agency_id": f.agency_id,
        "name": "Synthetic September travellers",
        "organizing_company_name": "Synthetic organizer",
        "support_contacts": [{"name": "Help desk", "phone_number": "9876543299"}],
        "recipient_opt_in_confirmed": True,
        "column_mappings": [
            {"sheet_name": "Contacts", "header_row": 1, "phone_column": 2, "name_column": 1}
        ],
    }


async def create_reviewed(sdk, draft):
    preview = await tool(sdk, "preview_contact_broadcast", {"draft": draft})
    request = {
        "draft": {**draft, "preview_sha256": preview["preview_sha256"]},
        "idempotency_key": "journey-create-broadcast-001",
    }
    created = await tool(sdk, "create_contact_broadcast", request)
    return preview, request, created


async def all_audience(sdk, broadcast_id, *, kind="recipients", page_size=2):
    rows, cursor = [], None
    while True:
        page = await tool(
            sdk,
            "list_whatsapp_audience",
            {"broadcast_id": broadcast_id, "kind": kind, "page_size": page_size, "cursor": cursor},
        )
        assert page["send_eligibility_evaluated"] is False
        rows.extend(page["items"])
        if not page["has_more"]:
            assert page["next_cursor"] is None and page["completeness"] == "complete"
            return rows
        assert page["completeness"] == "partial" and page["next_cursor"] != cursor
        cursor = page["next_cursor"]
