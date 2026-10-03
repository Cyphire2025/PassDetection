"""Disposable PostgreSQL: additive ticket schema, duplicate requests and upload leases."""

import asyncio
import hashlib
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import URL, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.mcp.artifacts import MCPArtifactService
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.native_transfer_dto import MCPNativeUploadRequest
from app.application.mcp.native_transfers import MCPNativeTransferService
from app.core.config.mcp import MCPSettings
from app.domain.mcp_section_permissions import SUPPORTED_WRITE_SECTIONS, WRITE_TOOL_SECTIONS
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_native_transfer_models import MCPNativeTransferModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.upload_security import UploadSecurityService
from app.presentation.api.v1.routes.mcp_native_transfers import router
from tests.integration.test_mcp_artifacts import Evidence, Scanner, Storage, pdf

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


async def test_native_ticket_retry_lease_and_revocation_under_actual_row_locks(test_settings):
    host, source, port = (
        os.environ["POSTGRES_HOST"],
        os.environ["POSTGRES_DB"],
        int(os.environ["POSTGRES_PORT"]),
    )
    if host not in {"localhost", "127.0.0.1"} or not (
        source.startswith("passdetection_ci_") or (source == "postgres" and port == 55436)
    ):
        pytest.fail("Only explicitly isolated local PostgreSQL is supported")
    name = "passdetection_ci_native_" + uuid.uuid4().hex[:12]
    url = URL.create(
        "postgresql+asyncpg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=host,
        port=port,
        database=source,
    )
    admin = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(url.set(database=name), poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = test_settings.model_copy(
        update={
            "mcp": MCPSettings(_env_file=None, enabled=True),
            "malware_quarantine_enabled": False,
        }
    )
    backend = Path(__file__).resolve().parents[2]
    now, user, agency, group, grant = (
        datetime.now(UTC),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )
    storage, scanner, evidence = Storage(), Scanner(), Evidence()
    security = UploadSecurityService(
        settings=settings, scanner=scanner, session_factory=lambda: evidence, storage=storage
    )

    async def migrate(revision):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            revision,
            cwd=backend,
            env={**os.environ, "POSTGRES_DB": name},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(process.communicate(), 90)
        assert process.returncode == 0, output.decode(errors="replace")[-3000:]

    def service(session):
        return MCPNativeTransferService(
            session,
            settings,
            artifacts=MCPArtifactService(session, settings, storage=storage, security=security),
        )

    async with admin.connect() as connection:
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        await migrate("0126_mcp_section_permissions")
        async with sessions() as session:
            session.add_all(
                [
                    UserModel(
                        id=user,
                        email=f"native-{user}@example.test",
                        hashed_password="synthetic",
                        full_name="Native concurrency",
                        role="super_admin",
                        is_active=True,
                    ),
                    AgencyModel(
                        id=agency, name="Native test agency", email="native-agency@example.test"
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    UserSecurityStateModel(
                        user_id=user,
                        session_version=1,
                        credential_state="active",
                        mfa_enabled_at=now,
                        mfa_secret_ciphertext="synthetic",
                    ),
                    ClientGroupModel(
                        id=group, agency_id=agency, name="Native test group", token=uuid.uuid4().hex
                    ),
                ]
            )
            control = await session.get(MCPControlModel, 1)
            control.enabled, control.write_enabled = True, True
            control.allowed_write_sections, control.allowed_write_tools = (
                sorted(SUPPORTED_WRITE_SECTIONS),
                sorted(WRITE_TOOL_SECTIONS),
            )
            row = MCPGrantModel(
                id=grant,
                user_id=user,
                client_id="global-connects-desktop",
                name="Native test device",
                resource=settings.mcp.resource,
                capabilities=["mcp:upload"],
                security_version=1,
                mfa_at=now,
                created_at=now,
                expires_at=now + timedelta(days=1),
                enabled=True,
                read_enabled=False,
                write_enabled=True,
                allowed_write_sections=sorted(SUPPORTED_WRITE_SECTIONS),
            )
            session.add(row)
            await session.flush()
            tokens = await MCPAuthorizationService(session, settings).issue_pair(row, now)
            await session.commit()

        async def retained_authority():
            async with sessions() as snapshot:
                await snapshot.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                return {
                    table: (
                        await snapshot.execute(
                            text(
                                f"SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb) FROM {table} t"
                            )
                        )
                    ).scalar_one()
                    for table in (
                        "mcp_control",
                        "mcp_grants",
                        "mcp_tokens",
                        "mcp_authorization_codes",
                        "mcp_connection_requests",
                    )
                }

        before = await retained_authority()
        await migrate("0127_mcp_native_transfers")
        assert await retained_authority() == before
        data = pdf()
        request = MCPNativeUploadRequest(
            purpose="document_pdf",
            agency_id=agency,
            group_id=group,
            document_type="visa",
            filename="visa.pdf",
            byte_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

        async def create(key):
            async with sessions() as session:
                result = await service(session).create_upload(tokens["access_token"], request, key)
                await session.commit()
                return result

        tickets = await asyncio.wait_for(
            asyncio.gather(*(create("parallel-native-key-0001") for _ in range(4))), 15
        )
        assert (
            len({item["id"] for item in tickets}) == 1
            and len({item["authorization_header"] for item in tickets}) == 1
        )
        app = FastAPI()
        app.state.settings, app.state.mcp_artifact_storage, app.state.mcp_artifact_security = (
            settings,
            storage,
            security,
        )
        app.include_router(router)

        async def database():
            async with sessions() as session:
                try:
                    yield session
                except BaseException:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db_session] = database
        async with AsyncClient(
            transport=ASGITransport(app), base_url="http://localhost:8000"
        ) as client:
            ticket = tickets[0]
            path = f"/mcp/native-transfers/{ticket['id']}/content"
            headers = {
                "Authorization": ticket["authorization_header"],
                "Content-Type": "application/pdf",
            }
            started, release = asyncio.Event(), asyncio.Event()

            async def held_body():
                started.set()
                await release.wait()
                yield data

            first = asyncio.create_task(client.put(path, headers=headers, content=held_body()))
            await asyncio.wait_for(started.wait(), 5)
            second = await client.put(path, headers=headers, content=data)
            assert second.status_code == 409 and scanner.calls == 0
            async with sessions() as session:
                row = await session.scalar(
                    select(MCPGrantModel).where(MCPGrantModel.id == grant).with_for_update()
                )
                row.enabled = False
                await session.commit()
            release.set()
            rejected = await asyncio.wait_for(first, 10)
            assert rejected.status_code == 403
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 0
                transfer = await session.get(MCPNativeTransferModel, uuid.UUID(ticket["id"]))
                assert transfer.status == "failed" and transfer.artifact_id is None
                row = await session.get(MCPGrantModel, grant)
                row.enabled = True
                await session.commit()
            ticket = await create("parallel-native-key-0002")
            path, headers["Authorization"] = (
                f"/mcp/native-transfers/{ticket['id']}/content",
                ticket["authorization_header"],
            )
            started.clear()
            release.clear()
            first = asyncio.create_task(client.put(path, headers=headers, content=held_body()))
            await asyncio.wait_for(started.wait(), 5)
            assert (await client.put(path, headers=headers, content=data)).status_code == 409
            release.set()
            assert (await asyncio.wait_for(first, 10)).status_code == 200
            assert (await client.put(path, headers=headers, content=data)).status_code == 200
            async with sessions() as session:
                assert await session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 1
                transfer = await session.get(MCPNativeTransferModel, uuid.UUID(ticket["id"]))
                assert transfer.status == "completed" and transfer.artifact_id is not None
        assert scanner.calls == 2 and len(storage.objects) == 1
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=:name"),
                {"name": name},
            )
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await admin.dispose()
