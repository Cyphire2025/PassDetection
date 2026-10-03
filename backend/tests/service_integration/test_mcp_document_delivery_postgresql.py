"""Original authority and exact-plan contention in a newly isolated local database."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import URL, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp.document_delivery import document_delivery_operations
from app.application.mcp.operations import MCPOperationService
from app.core.config.mcp import MCPSettings
from app.domain.mcp_read_sections import SUPPORTED_READ_SECTIONS
from app.domain.mcp_section_permissions import SUPPORTED_WRITE_SECTIONS, WRITE_TOOL_SECTIONS
from app.infrastructure.database.mcp_document_delivery_models import MCPDocumentDeliveryOutboxModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.models import DocumentWhatsAppDeliveryModel
from app.infrastructure.whatsapp import document_delivery_runtime, template_settings
from app.presentation.api.v1.routes import document_distribution_delivery_preview
from app.presentation.mcp.document_delivery_snapshots import document_delivery_snapshot
from tests.integration.test_mcp_operations import seed_identity
from tests.traveller_delivery_fixtures import seed_traveller_delivery

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="requires isolated local PostgreSQL",
)]


async def test_duplicate_confirmation_and_revocation_wait_on_original_provider_barrier(test_settings, monkeypatch):
    host, port, source = os.environ["POSTGRES_HOST"], int(os.environ["POSTGRES_PORT"]), os.environ["POSTGRES_DB"]
    if host not in {"127.0.0.1", "localhost"} or not (
        source.startswith("passdetection_ci_") or (source == "postgres" and port == 55436)
    ):
        pytest.fail("Only the explicitly isolated local PostgreSQL instance is supported")
    name = "passdetection_ci_document_delivery_" + uuid.uuid4().hex[:12]
    url = URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=host, port=port, database=source)
    admin = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(url.set(database=name), poolclass=NullPool,
        connect_args={"server_settings": {"lock_timeout": "10000", "statement_timeout": "20000"}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = test_settings.model_copy(update={"mcp": MCPSettings(_env_file=None, enabled=True),
        "whatsapp_access_token": "synthetic-document-token", "whatsapp_phone_number_id": "synthetic-sender",
        "whatsapp_document_template_name": "document_template", "whatsapp_delivery_concurrency": 1})
    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", "alembic", "upgrade",
            "0128_mcp_document_delivery", cwd=Path(__file__).resolve().parents[2],
            env={**os.environ, "POSTGRES_DB": name}, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
        output, _ = await asyncio.wait_for(process.communicate(), 100)
        assert process.returncode == 0, output.decode(errors="replace")[-3000:]
        async with sessions() as session:
            control = await session.get(MCPControlModel, 1)
            control.enabled, control.write_enabled = True, True
            control.allowed_read_sections, control.allowed_write_sections = sorted(SUPPORTED_READ_SECTIONS), sorted(SUPPORTED_WRITE_SECTIONS)
            control.allowed_write_tools = sorted(WRITE_TOOL_SECTIONS)
            user, grants, tokens = await seed_identity(session, settings, email=f"documents-{uuid.uuid4()}@example.test")
            for grant in grants:
                grant.capabilities = ["mcp:read", "mcp:communicate"]
            await session.commit()
            context = await seed_traveller_delivery(session, SimpleNamespace(headers={}))
            payload = {"agency_id": str(context.agency.id), "group_id": str(context.group.id),
                "batch_id": str(context.batch.id), "document_ids": sorted(str(row.id) for row in context.documents),
                "message_content_1": "Your prepared PDF.", "message_content_2": "Check the attached details."}
            original_grant_id = grants[0].id
        monkeypatch.setattr(document_distribution_delivery_preview, "get_settings", lambda: settings)
        monkeypatch.setattr(template_settings, "get_settings", lambda: settings)
        monkeypatch.setattr(document_delivery_runtime, "get_settings", lambda: settings)
        monkeypatch.setattr(document_delivery_runtime, "AsyncSessionFactory", sessions)
        monkeypatch.setattr(document_delivery_runtime, "MinioStorageRepository", lambda: SimpleNamespace(
            get_file=AsyncMock(return_value=b"%PDF-1.7\nsynthetic fixture\n%%EOF")))
        upload = AsyncMock(return_value="synthetic-media")
        monkeypatch.setattr(document_delivery_runtime, "upload_whatsapp_document", upload)
        monkeypatch.setattr(document_delivery_runtime, "_propagate_first_released_document_batch", AsyncMock(return_value=0))

        async def invoke(name, input, connection=0, callback=document_delivery_snapshot):
            async with sessions() as session:
                result = await MCPOperationService(session, settings,
                    document_delivery_operations(settings, callback)).execute(access_token=tokens[connection],
                    operation_name=name, idempotency_key="pg-exact-" + name + "-0001", payload=input)
                await session.commit()
                return result

        prepared = await invoke("prepare_whatsapp_document_delivery", payload)
        confirmation = {"plan_id": prepared["data"]["plan_id"], "plan_hash": prepared["data"]["plan_hash"], "user_confirmed": True}
        entered, release, second_started = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def held_snapshot(*args, **kwargs):
            entered.set()
            await asyncio.wait_for(release.wait(), 10)
            return await document_delivery_snapshot(*args, **kwargs)

        first = asyncio.create_task(invoke("confirm_whatsapp_document_delivery", confirmation, callback=held_snapshot))
        await asyncio.wait_for(entered.wait(), 5)

        async def duplicate():
            second_started.set()
            return await invoke("confirm_whatsapp_document_delivery", confirmation, connection=1)

        second = asyncio.create_task(duplicate())
        await second_started.wait()
        await asyncio.sleep(0.15)
        assert not second.done()
        release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), 15)
        assert results[0] == results[1]
        send_batch_id = uuid.UUID(results[0]["data"]["send_batch_id"])
        async with sessions() as session:
            assert await session.scalar(select(func.count()).select_from(MCPDocumentDeliveryOutboxModel)) == 1
            assert await session.scalar(select(func.count()).select_from(DocumentWhatsAppDeliveryModel)) == 2
            delivery_id = await session.scalar(select(DocumentWhatsAppDeliveryModel.id).where(
                DocumentWhatsAppDeliveryModel.send_batch_id == send_batch_id).order_by(DocumentWhatsAppDeliveryModel.id))

        provider_entered, provider_release, revoke_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
        provider_calls = []

        async def provider(**kwargs):
            provider_calls.append(kwargs["to_number"])
            provider_entered.set()
            await asyncio.wait_for(provider_release.wait(), 10)
            return "wamid." + uuid.uuid4().hex

        monkeypatch.setattr(document_delivery_runtime, "send_whatsapp_document_template", provider)
        worker = asyncio.create_task(document_delivery_runtime.run_document_whatsapp_broadcast(
            send_batch_id=str(send_batch_id), _delivery_id=delivery_id))
        await asyncio.wait_for(provider_entered.wait(), 10)

        async def revoke():
            async with sessions() as session:
                revoke_started.set()
                await session.execute(update(MCPGrantModel).where(MCPGrantModel.id == original_grant_id).values(enabled=False))
                await session.commit()

        revocation = asyncio.create_task(revoke())
        await revoke_started.wait()
        await asyncio.sleep(0.15)
        assert not revocation.done()
        provider_release.set()
        await asyncio.wait_for(asyncio.gather(worker, revocation), 15)
        await document_delivery_runtime.run_document_whatsapp_broadcast(send_batch_id=str(send_batch_id))
        assert len(provider_calls) == 1 and upload.await_count == 1
        async with sessions() as session:
            counts = dict((await session.execute(select(DocumentWhatsAppDeliveryModel.status, func.count())
                .group_by(DocumentWhatsAppDeliveryModel.status))).all())
            assert counts == {"submitted": 1, "failed": 1}
    finally:
        await engine.dispose()
        await admin.dispose()
        print(f"MCP_DOCUMENT_DELIVERY_DATABASE_RETAINED={name}")
