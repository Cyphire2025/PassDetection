"""Authenticated HTTP artifact contract with real SQL and existing PDF security validation."""

from __future__ import annotations

import asyncio
import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from sqlalchemy import func, select

from app.application.mcp.artifacts import ArtifactError, MCPArtifactService, transfer_slot
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import pkce_challenge
from app.core.config.mcp import MCPSettings
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportHistoryRepository,
)
from app.infrastructure.security.upload_security import UploadSecurityService
from app.infrastructure.security.upload_validator import (
    MalwareScannerUnavailableError,
    MalwareScanRejectedError,
)
from app.infrastructure.storage.minio_repository import ObjectIntegrityMetadata
from app.presentation.api.v1.routes.mcp_artifacts import router


class Storage:
    def __init__(self):
        self.objects = {}
        self.read_sizes = []
        self.corrupt = False

    async def put_transfer(self, source, *, key, size, sha256, media_type):
        assert key not in self.objects
        source.seek(0)
        chunks = []
        while part := source.read(65536):
            chunks.append(part)
        data = b"".join(chunks)
        assert len(data) == size and hashlib.sha256(data).hexdigest() == sha256
        self.objects[key] = (data, sha256, media_type)

    async def stat_file(self, key):
        data, sha256, media = self.objects[key]
        return ObjectIntegrityMetadata(len(data), sha256, media)

    async def stream_file(self, key, *, start, expected_bytes, chunk_size):
        data = self.objects[key][0]
        if self.corrupt:
            data = b"X" + data[1:]
        for offset in range(start, len(data), min(chunk_size, 17)):
            part = data[offset : offset + min(chunk_size, 17)]
            self.read_sizes.append(len(part))
            yield part


class Scanner:
    error = None
    calls = 0

    def scan(self, content):
        self.calls += 1
        if self.error:
            raise self.error("fixture scan error")


class Evidence:
    def __init__(self):
        self.records = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    def add(self, record):
        self.records.append(record)

    async def commit(self):
        return None


async def chunks(data):
    for offset in range(0, len(data), 11):
        yield data[offset : offset + 11]


async def test_local_file_preflight_requires_current_file_authority_without_read_scope(artifacts):
    token, principal = await artifacts.connect(["mcp:upload"])
    headers = {"Authorization": f"Bearer {token}"}
    result = await artifacts.client.get("/mcp/artifacts/authority", headers=headers)
    assert result.status_code == 200 and result.json() == {"authorized": True, "capabilities": ["mcp:upload"]}
    assert result.headers["cache-control"] == "no-store"
    denied = await artifacts.client.get("/mcp/artifacts/authority?capability=mcp:export", headers=headers)
    assert denied.status_code == 403
    grant = await artifacts.session.get(MCPGrantModel, principal.grant_id)
    grant.revoked_at = datetime.now(UTC)
    await artifacts.session.commit()
    revoked = await artifacts.client.get("/mcp/artifacts/authority", headers=headers)
    assert revoked.status_code in {401, 403}
    assert "capabilities" not in revoked.json()


def pdf():
    writer, output = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)
    return output.getvalue()


@pytest.fixture
async def artifacts(db_session, test_settings):
    now = datetime.now(UTC)
    settings = test_settings.model_copy(
        update={"mcp": MCPSettings(enabled=True), "malware_quarantine_enabled": False}
    )
    actor = UserModel(
        id=uuid.uuid4(),
        email="artifact@example.test",
        hashed_password="fixture",
        full_name="Fixture",
        role="super_admin",
        is_active=True,
    )
    agency = AgencyModel(id=uuid.uuid4(), name="Artifact fixture", email="agency@example.test")
    db_session.add_all([actor, agency])
    await db_session.flush()
    group = ClientGroupModel(
        id=uuid.uuid4(), agency_id=agency.id, name="Fixture trip", token=uuid.uuid4().hex
    )
    db_session.add_all(
        [
            group,
            MCPControlModel(id=1, enabled=True),
            UserSecurityStateModel(
                user_id=actor.id,
                session_version=1,
                credential_state="active",
                mfa_enabled_at=now,
                mfa_secret_ciphertext="encrypted-fixture",
            ),
        ]
    )
    await db_session.flush()
    auth = MCPAuthorizationService(db_session, settings)
    verifier = "v" * 64

    async def connect(scopes=None):
        code = await auth.authorize(
            user_id=actor.id,
            security_version=1,
            mfa_at=now,
            client_id="global-connects-desktop",
            redirect_uri="http://127.0.0.1:8765/callback",
            resource="http://localhost:8000/mcp",
            challenge=pkce_challenge(verifier),
            scopes=scopes or ["mcp:read", "mcp:upload", "mcp:export"],
            name="Artifacts fixture",
        )
        tokens = await auth.exchange_code(
            code=code,
            verifier=verifier,
            client_id="global-connects-desktop",
            redirect_uri="http://127.0.0.1:8765/callback",
            resource="http://localhost:8000/mcp",
        )
        principal = await auth.verify_access(tokens["access_token"])
        await db_session.commit()
        return tokens["access_token"], principal

    token, principal = await connect()
    storage, scanner, evidence = Storage(), Scanner(), Evidence()
    security = UploadSecurityService(
        settings=settings, scanner=scanner, session_factory=lambda: evidence, storage=storage
    )
    app = FastAPI()
    app.state.settings, app.state.mcp_artifact_storage, app.state.mcp_artifact_security = (
        settings,
        storage,
        security,
    )
    app.include_router(router)

    async def database():
        yield db_session

    app.dependency_overrides[get_db_session] = database
    async with AsyncClient(
        transport=ASGITransport(app),
        base_url="http://localhost:8000",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield SimpleNamespace(
            session=db_session,
            settings=settings,
            user=actor,
            agency=agency,
            group=group,
            storage=storage,
            scanner=scanner,
            evidence=evidence,
            client=client,
            security=security,
            connect=connect,
            principal=principal,
            token=token,
            service=MCPArtifactService(db_session, settings, storage=storage, security=security),
        )


async def upload(f, data=None, **overrides):
    await f.session.refresh(f.agency)
    await f.session.refresh(f.group)
    data = data if data is not None else pdf()
    return await f.client.post(
        "/mcp/artifacts/uploads",
        params={
            "agency_id": str(f.agency.id),
            "group_id": str(f.group.id),
            "filename": "../../passport.pdf",
            **overrides.pop("params", {}),
        },
        content=chunks(data),
        headers={
            "Content-Type": "application/pdf",
            "X-Artifact-Size": str(len(data)),
            "X-Artifact-SHA256": hashlib.sha256(data).hexdigest(),
            **overrides.pop("headers", {}),
        },
        **overrides,
    )


async def prepared(f):
    history = await PassportExportHistoryRepository(f.session).record(
        group_id=f.group.id,
        agency_id=f.agency.id,
        export_kind="passport_excel",
        export_mode="all",
        request_id=uuid.uuid4(),
        snapshot_submission_ids=[],
        exported_submission_ids=[],
        exported_people_snapshot=[],
        created_by_user_id=f.user.id,
        actor_email=f.user.email,
    )
    data = b"generated-workbook-fixture" * 30
    result = await f.service.prepare_export(
        f.principal,
        agency_id=f.agency.id,
        group_id=f.group.id,
        purpose="passport_excel",
        filename="people.xlsx",
        body=chunks(data),
        export_history_id=history.id,
    )
    await f.session.commit()
    return result, history, data


async def test_streamed_pdf_scanned_bound_and_no_business_ingestion(artifacts):
    f = artifacts
    response = await upload(f)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["business_ingestion"] == "not_started" and result["filename"] == "passport.pdf"
    assert result["sha256"] == hashlib.sha256(pdf()).hexdigest()
    assert f.scanner.calls == 1 and f.evidence.records[0].scan_status == "clean"
    row = await f.session.scalar(select(MCPArtifactModel))
    assert row.handle_hash != result["artifact_id"] and row.grant_id == f.principal.grant_id
    assert "storage_key" not in result
    download = await f.client.get(result["content_path"])
    assert download.status_code == 200 and download.content == pdf()
    assert max(f.storage.read_sizes) <= 65536
    logs = (await f.session.scalars(select(AuditLogModel))).all()
    assert all(result["artifact_id"] not in str(log.metadata_json) for log in logs)


@pytest.mark.parametrize(
    "error,status", [(MalwareScannerUnavailableError, 503), (MalwareScanRejectedError, 422)]
)
async def test_scanner_errors_fail_closed_without_artifact(artifacts, error, status):
    f = artifacts
    f.scanner.error = error
    response = await upload(f)
    assert response.status_code == status, response.text
    assert not f.storage.objects
    assert await f.session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 0
    assert f.evidence.records[0].disposition == "rejected"


async def test_checksum_format_size_and_group_boundaries_before_storage(artifacts):
    f = artifacts
    wrong_agency = uuid.uuid4()
    assert (await upload(f, params={"agency_id": str(wrong_agency)})).status_code == 404
    assert (await upload(f, headers={"X-Artifact-SHA256": "0" * 64})).status_code == 422
    assert (await upload(f, data=b"not a pdf")).status_code == 422
    assert (
        await upload(f, headers={"X-Artifact-Size": str(f.settings.upload_max_file_size_bytes + 1)})
    ).status_code == 422
    assert (await upload(f, headers={"Content-Type": "text/plain"})).status_code == 415
    assert not f.storage.objects


async def test_foreign_grant_and_dashboard_token_cannot_read(artifacts):
    f = artifacts
    result = (await upload(f)).json()
    other_token, _ = await f.connect()
    assert (
        await f.client.get(
            result["content_path"], headers={"Authorization": f"Bearer {other_token}"}
        )
    ).status_code == 404
    assert (
        await f.client.get(
            result["content_path"], headers={"Authorization": "Bearer dashboard.jwt.fixture"}
        )
    ).status_code == 401
    assert (
        await f.client.get(result["content_path"], headers={"Authorization": ""})
    ).status_code == 401


@pytest.mark.parametrize("change", ["revoke", "role", "disabled", "scope", "expired"])
async def test_each_new_download_rechecks_current_authority(artifacts, change):
    f = artifacts
    result = (await upload(f)).json()
    grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
    if change == "revoke":
        grant.revoked_at = datetime.now(UTC)
    if change == "role":
        f.user.role = "agency_admin"
    if change == "disabled":
        (await f.session.get(MCPControlModel, 1)).enabled = False
    if change == "scope":
        grant.capabilities = ["mcp:read"]
    if change == "expired":
        grant.created_at = datetime.now(UTC) - timedelta(days=2)
        grant.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await f.session.commit()
    assert (await f.client.get(result["content_path"])).status_code in {400, 401, 403, 503}


async def test_verified_ack_is_delayed_idempotent_and_uses_shared_history(artifacts):
    f = artifacts
    result, history, data = await prepared(f)
    path = f"/mcp/artifacts/{result['artifact_id']}/delivery"
    payload = {"byte_size": len(data), "sha256": result["sha256"]}
    assert history.status == "prepared"
    assert (await f.client.post(path, json=payload)).status_code == 409
    # A failed request rolls back/expires ORM state; refresh before direct inspection.
    await f.session.refresh(history)
    assert history.status == "prepared"
    response = await f.client.get(result["content_path"])
    assert response.content == data and response.headers["x-artifact-sha256"] == payload["sha256"]
    await f.session.refresh(history)
    assert history.status == "prepared"
    assert (await f.client.post(path, json={**payload, "sha256": "0" * 64})).status_code == 422
    first = await f.client.post(path, json=payload)
    assert first.status_code == 200, first.text
    second = await f.client.post(path, json=payload)
    assert second.json()["delivered_at"] == first.json()["delivered_at"]
    await f.session.refresh(history)
    assert history.status == "completed"
    assert (
        await f.session.scalar(
            select(func.count())
            .select_from(AuditLogModel)
            .where(AuditLogModel.action == "passport_group_exported")
        )
        == 1
    )


async def test_interrupted_or_corrupt_stream_never_completes_delivery(artifacts):
    f = artifacts
    result, history, _ = await prepared(f)
    row = await f.service.get(f.principal, result["artifact_id"])
    stream = f.service.stream(f.principal, result["artifact_id"], row)
    await anext(stream)
    await stream.aclose()
    assert row.download_completed_at is None and history.status == "prepared"
    f.storage.corrupt = True
    with pytest.raises(Exception, match="checksum"):
        async for _ in f.service.stream(f.principal, result["artifact_id"], row):
            pass
    assert row.download_completed_at is None and history.status == "prepared"


async def test_expiry_and_capacity_fail_closed(artifacts):
    f = artifacts
    result = (await upload(f)).json()
    row = await f.session.scalar(select(MCPArtifactModel))
    row.created_at = datetime.now(UTC) - timedelta(hours=2)
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await f.session.commit()
    assert (await f.client.get(result["content_path"])).status_code == 404
    async with transfer_slot(), transfer_slot():
        with pytest.raises(ArtifactError, match="capacity"):
            async with transfer_slot():
                pass
    async with transfer_slot():
        pass


async def test_checkpoint_changes_and_revoked_ack_cannot_complete(artifacts):
    f = artifacts
    result, history, data = await prepared(f)
    assert (await f.client.get(result["content_path"])).status_code == 200
    history.pending_recipient_count = 1
    await f.session.commit()
    path = f"/mcp/artifacts/{result['artifact_id']}/delivery"
    payload = {"byte_size": len(data), "sha256": result["sha256"]}
    assert (await f.client.post(path, json=payload)).status_code == 409
    await f.session.refresh(history)
    assert history.status == "prepared"
    grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
    grant.revoked_at = datetime.now(UTC)
    await f.session.commit()
    assert (await f.client.post(path, json=payload)).status_code in {400, 401, 403}
    await f.session.refresh(history)
    assert history.status == "prepared"


async def test_deployment_capability_disabled_after_grant_denies_new_transfer_calls(artifacts):
    f = artifacts
    result, history, data = await prepared(f)
    assert (await f.client.get(result["content_path"])).status_code == 200
    f.settings.mcp.enabled_capabilities = ["mcp:read"]
    base = f"/mcp/artifacts/{result['artifact_id']}"
    assert (await f.client.get(base)).status_code == 403
    assert (await f.client.get(base + "/content")).status_code == 403
    assert (
        await f.client.post(
            base + "/delivery", json={"byte_size": len(data), "sha256": result["sha256"]}
        )
    ).status_code == 403
    await f.session.refresh(history)
    assert history.status == "prepared"


async def test_actual_oversize_rejected_and_cancellation_closes_staging_file(
    artifacts, monkeypatch
):
    from app.application.mcp import artifacts as module

    f = artifacts
    maximum = f.settings.upload_max_file_size_bytes
    opened = []
    original = module.tempfile.TemporaryFile

    def temporary(*args, **kwargs):
        target = original(*args, **kwargs)
        opened.append(target)
        return target

    monkeypatch.setattr(module.tempfile, "TemporaryFile", temporary)

    async def too_large():
        yield b"x" * (maximum + 1)

    async def cancelled():
        yield b"%PDF-"
        raise asyncio.CancelledError()

    for body, error in [(too_large(), ArtifactError), (cancelled(), asyncio.CancelledError)]:
        with pytest.raises(error):
            await f.service.stage_pdf(
                f.principal,
                agency_id=f.agency.id,
                group_id=f.group.id,
                filename="test.pdf",
                body=body,
                expected_size=1,
                expected_sha256="0" * 64,
            )
    assert all(target.closed for target in opened)
    assert not f.storage.objects and f.scanner.calls == 0
    async with transfer_slot(), transfer_slot():
        pass


async def test_storage_conditional_write_never_overwrites(test_settings):
    from app.domain.exceptions.exceptions import StorageError
    from app.infrastructure.storage.mcp_artifact_storage import MCPArtifactStorage

    writes = []

    class Client:
        def put_object(self, **kwargs):
            assert kwargs["IfNoneMatch"] == "*"
            if writes:
                raise RuntimeError("precondition failed")
            writes.append(kwargs["Body"].read())

    adapter = object.__new__(MCPArtifactStorage)
    adapter._client = Client()
    adapter.settings = test_settings.s3
    kwargs = dict(
        key="mcp-transfers/v1/test-fixture",
        size=4,
        sha256=hashlib.sha256(b"safe").hexdigest(),
        media_type="application/pdf",
    )
    await adapter.put_transfer(io.BytesIO(b"safe"), **kwargs)
    with pytest.raises(StorageError):
        await adapter.put_transfer(io.BytesIO(b"evil"), **kwargs)
    assert writes == [b"safe"]


async def test_storage_cancellation_drains_worker_before_source_can_close(test_settings):
    import threading

    from app.infrastructure.storage.mcp_artifact_storage import MCPArtifactStorage

    entered, finish = threading.Event(), threading.Event()
    reads = []

    class Client:
        def put_object(self, **kwargs):
            entered.set()
            assert finish.wait(5)
            reads.append(kwargs["Body"].read())

    adapter = object.__new__(MCPArtifactStorage)
    adapter._client = Client()
    adapter.settings = test_settings.s3
    source = io.BytesIO(b"safe")
    task = asyncio.create_task(
        adapter.put_transfer(
            source,
            key="mcp-transfers/v1/cancel-fixture",
            size=4,
            sha256=hashlib.sha256(b"safe").hexdigest(),
            media_type="application/pdf",
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reads == [b"safe"]
    finally:
        finish.set()
        await asyncio.gather(task, return_exceptions=True)
        source.close()
