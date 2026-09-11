"""Actual PostgreSQL HTTP -> welcome worker -> signed receipt -> document worker."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import URL, delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config.settings import get_settings
from app.infrastructure.database.models import (
    AgencyModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.whatsapp import document_delivery_runtime, traveller_welcome_runtime
from app.main import create_application
from app.presentation.api.v1.routes import document_distribution_delivery, traveller_welcome
from tests.traveller_delivery_fixtures import (
    FATHER_PHONE,
    MOTHER_PHONE,
    QUALIFIER_PHONE,
    seed_traveller_delivery,
)

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="requires isolated migrated PostgreSQL",
)]
PREFIX = "/api/v1/document-distribution"


@pytest.mark.asyncio
@pytest.mark.parametrize("document_type", ["visa", "flight_ticket"])
async def test_real_http_receipt_unlocks_only_actual_traveller_documents(test_settings, monkeypatch, document_type):
    url = URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=os.environ["POSTGRES_HOST"],
        port=int(os.environ["POSTGRES_PORT"]), database=os.environ["POSTGRES_DB"])
    engine = create_async_engine(url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_application(settings=test_settings, initialize_rate_limit_redis=False)

    async def database():
        async with factory() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_db_session] = database
    settings = get_settings()
    monkeypatch.setattr(settings, "whatsapp_access_token", "synthetic-provider-token")
    monkeypatch.setattr(settings, "whatsapp_phone_number_id", "synthetic-sender")
    monkeypatch.setattr(settings, "whatsapp_document_template_name", "document-template")
    monkeypatch.setattr(settings, "whatsapp_app_secret", "synthetic-webhook-secret")
    monkeypatch.setattr(traveller_welcome, "publish_whatsapp_task", AsyncMock())
    monkeypatch.setattr(document_distribution_delivery, "publish_whatsapp_task", AsyncMock())
    monkeypatch.setattr(traveller_welcome_runtime, "AsyncSessionFactory", factory)
    monkeypatch.setattr(document_delivery_runtime, "AsyncSessionFactory", factory)
    monkeypatch.setattr(document_delivery_runtime, "MinioStorageRepository",
        lambda: SimpleNamespace(get_file=AsyncMock(return_value=b"%PDF-1.7\nsynthetic\n%%EOF")))
    monkeypatch.setattr(document_delivery_runtime, "upload_whatsapp_document", AsyncMock(return_value="media-fixture"))
    monkeypatch.setattr(document_delivery_runtime, "_propagate_first_released_document_batch", AsyncMock(return_value=0))
    welcomes, documents = [], []

    async def provider_welcome(**kwargs):
        provider_id = f"wamid.welcome.{uuid.uuid4()}"
        welcomes.append((kwargs["to_number"], provider_id))
        return provider_id

    async def provider_document(**kwargs):
        documents.append(kwargs["to_number"])
        return f"wamid.document.{uuid.uuid4()}"

    monkeypatch.setattr(traveller_welcome_runtime, "send_whatsapp_template", provider_welcome)
    monkeypatch.setattr(document_delivery_runtime, "send_whatsapp_document_template", provider_document)
    context = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            async with factory() as session:
                context = await seed_traveller_delivery(session, client, document_type=document_type)
            preview_url = f"{PREFIX}/groups/{context.group.id}/whatsapp-welcome-preview"
            preview_response = await client.get(preview_url)
            assert preview_response.status_code == 200, preview_response.text
            preview = preview_response.json()
            queued = await client.post(f"{PREFIX}/groups/{context.group.id}/whatsapp-welcome-send", json={
                "phone_numbers": [MOTHER_PHONE, FATHER_PHONE], "preview_token": preview["preview_token"],
                "source_broadcast_id": preview["source_broadcast_id"],
            })
            assert queued.status_code == 202, queued.text
            await traveller_welcome_runtime.run_traveller_welcome_broadcast(batch_id=queued.json()["batch_id"])
            await traveller_welcome_runtime.run_traveller_welcome_broadcast(batch_id=queued.json()["batch_id"])
            assert {phone for phone, _ in welcomes} == {MOTHER_PHONE, FATHER_PHONE}
            assert len(welcomes) == 2
            body = {"document_ids": [str(row.id) for row in context.documents],
                    "message_content_1": "Your travel document", "message_content_2": "Safe travels"}
            document_url = f"{PREFIX}/batches/{context.batch.id}/whatsapp-send"
            assert (await client.post(document_url, json=body)).status_code == 409
            receipts = json.dumps({"entry": [{"changes": [{"value": {"statuses": [
                {"id": provider_id, "status": "delivered", "timestamp": str(int(datetime.now(tz=UTC).timestamp()))}
                for _, provider_id in welcomes
            ]}}]}]}).encode()
            signature = hmac.new(b"synthetic-webhook-secret", receipts, hashlib.sha256).hexdigest()
            webhook = await client.post("/api/v1/whatsapp/webhook", content=receipts,
                headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=" + signature})
            assert webhook.status_code == 200, webhook.text
            assert (await client.get(preview_url)).json()["summary"]["already_welcomed"] == 2
            sent = await client.post(document_url, json=body)
            assert sent.status_code == 202, sent.text
            await document_delivery_runtime.run_document_whatsapp_broadcast(send_batch_id=sent.json()["send_batch_id"])
            assert sorted(documents) == sorted([MOTHER_PHONE, FATHER_PHONE])
            assert QUALIFIER_PHONE not in documents
            async with factory() as session:
                deliveries = (await session.scalars(select(DocumentWhatsAppDeliveryModel).where(
                    DocumentWhatsAppDeliveryModel.group_id == context.group.id,
                ))).all()
                assert len(deliveries) == 2 and all(row.status == "submitted" for row in deliveries)
    finally:
        if context:
            async with factory() as session:
                await session.execute(delete(PassportSubmissionModel).where(
                    PassportSubmissionModel.agency_id == context.agency.id,
                ))
                await session.execute(delete(AgencyModel).where(AgencyModel.id == context.agency.id))
                await session.execute(delete(UserModel).where(UserModel.id == context.user.id))
                await session.commit()
        await engine.dispose()
