from __future__ import annotations

import asyncio
import io
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool
from starlette.requests import Request

from app.domain.entities.entities import ClientGroup, GroupStatus
from app.domain.value_objects.upload_configuration import MAX_PUBLIC_DOCUMENT_BYTES
from app.infrastructure.security.upload_validator import ValidatedUpload
from app.presentation.api.v1.routes.passport_routes import public_security, public_upload
from app.presentation.api.v1.routes.passport_routes.public_upload_documents import (
    validate_public_upload_documents,
)
from app.presentation.middleware.rate_limit import RateLimitMiddleware


def _group(**kwargs):
    return ClientGroup.create(
        "Synthetic link", "synthetic-link", uuid.uuid4(), uuid.uuid4(),
        allow_files_from_device=True, require_selfie=True, **kwargs,
    )


def _file(name="synthetic.pdf"):
    return UploadFile(file=io.BytesIO(b"synthetic"), filename=name)


async def test_parallel_previews_leave_connections_for_security_evidence(monkeypatch, tmp_path):
    """Two capability lookups must not starve independent security writes."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'preview-pool.db'}",
        poolclass=AsyncAdaptedQueuePool, pool_size=2, max_overflow=0, pool_timeout=0.2,
    )
    sessions = async_sessionmaker(engine)
    lookups = asyncio.Barrier(2)

    async def lookup(session):
        await session.execute(text("SELECT 1"))
        await lookups.wait()
        return _group()

    async def validate(*_args, **_kwargs):
        async with sessions() as evidence:
            await evidence.execute(text("INSERT INTO scan_evidence DEFAULT VALUES"))
            await evidence.commit()
        return ValidatedUpload(b"jpeg", "image/jpeg", "page.jpg", 120, 160, "JPEG")

    monkeypatch.setattr(public_upload, "ClientGroupRepository", lambda session: Mock(
        get_by_token=lambda _token: lookup(session),
    ))
    monkeypatch.setattr(public_upload, "_validated_upload_file", validate)

    async def prepare():
        async with sessions() as session:
            return await public_upload.prepare_public_upload_file(
                token="synthetic-link", file=_file(), purpose="passport",
                upload_session_id="a" * 40, session=session,
            )

    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE scan_evidence (id INTEGER PRIMARY KEY)"))
        results = await asyncio.gather(prepare(), prepare(), return_exceptions=True)
        assert all(not isinstance(result, BaseException) and result.status_code == 200 for result in results), results
        async with sessions() as session:
            assert await session.scalar(text("SELECT count(*) FROM scan_evidence")) == 2
    finally:
        await engine.dispose()


@pytest.mark.parametrize("state", [GroupStatus.CLOSED, GroupStatus.ARCHIVED, GroupStatus.DELETED, None])
async def test_prepare_rejects_invalid_token_before_file_read_or_decode(monkeypatch, state):
    group = _group()
    group.status = state
    groups = Mock(get_by_token=AsyncMock(return_value=group if state else None))
    monkeypatch.setattr(public_upload, "ClientGroupRepository", lambda _: groups)
    decoder = AsyncMock()
    monkeypatch.setattr(public_upload, "_validated_upload_file", decoder)
    upload = _file()
    with pytest.raises(HTTPException) as exc:
        await public_upload.prepare_public_upload_file(
            token="synthetic-link", file=upload, purpose="passport", upload_session_id="a" * 40, session=AsyncMock(),
        )
    assert exc.value.status_code == 404
    assert upload.file.tell() == 0
    decoder.assert_not_awaited()


@pytest.mark.parametrize("purpose", ["passport", "visa"])
async def test_prepare_respects_disabled_upload_method(monkeypatch, purpose):
    group = _group(upload_configuration={"passport_enabled": False, "visa_photo_upload": False})
    monkeypatch.setattr(public_upload, "ClientGroupRepository", lambda _: Mock(get_by_token=AsyncMock(return_value=group)))
    decoder = AsyncMock()
    monkeypatch.setattr(public_upload, "_validated_upload_file", decoder)
    with pytest.raises(HTTPException) as exc:
        await public_upload.prepare_public_upload_file(
            token=group.token, file=_file(), purpose=purpose, upload_session_id="a" * 40, session=AsyncMock(),
        )
    assert exc.value.status_code == 400
    decoder.assert_not_awaited()


@pytest.mark.parametrize("purpose", ["passport", "visa"])
async def test_prepare_multipart_contract_returns_private_jpeg(monkeypatch, purpose):
    group = _group()
    monkeypatch.setattr(public_upload, "ClientGroupRepository", lambda _: Mock(get_by_token=AsyncMock(return_value=group)))
    result = ValidatedUpload(b"jpeg-pixels", "image/jpeg", "page.jpg", 120, 160, "JPEG")
    decoder = AsyncMock(return_value=result)
    monkeypatch.setattr(public_upload, "_validated_upload_file", decoder)
    app = FastAPI()
    app.include_router(public_upload.router)
    app.dependency_overrides[public_upload.get_db_session] = lambda: AsyncMock()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/upload/synthetic-link/prepare-file", data={"purpose": purpose},
            files={"file": ("synthetic.pdf", b"synthetic", "application/pdf")},
            headers={"X-Upload-Session-ID": "a" * 40},
        )
    assert response.status_code == 200
    assert response.content == b"jpeg-pixels"
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "private, no-store"
    assert decoder.call_args.kwargs["public_device_file"] is True
    assert decoder.call_args.kwargs["max_size_bytes"] == (MAX_PUBLIC_DOCUMENT_BYTES if purpose == "passport" else None)


async def test_persistence_uses_same_public_validator_and_keeps_visa_image_ten_mb_limit():
    decoder = AsyncMock(return_value=ValidatedUpload(b"jpeg", "image/jpeg", "page.jpg", 120, 160, "JPEG"))
    result = await validate_public_upload_documents(
        group=_group(), acquisition_mode="file", visa_photo_source="file",
        file=_file(), passport_back_file=_file(), passport_photo_file=_file(),
        passport_cover_file=None, passport_back_cover_file=None, validator=decoder,
    )
    assert result["file_content"] == b"jpeg"
    assert result["passport_photo"] == (b"jpeg", "image/jpeg", "page.jpg")
    assert [call.kwargs["max_size_bytes"] for call in decoder.call_args_list] == [MAX_PUBLIC_DOCUMENT_BYTES, MAX_PUBLIC_DOCUMENT_BYTES, None]
    assert all(call.kwargs["public_device_file"] for call in decoder.call_args_list)


async def test_public_device_file_cannot_skip_public_validator(monkeypatch):
    service = Mock(validate_public_file=AsyncMock(return_value="normalized"), validate_image=AsyncMock())
    monkeypatch.setattr(public_security, "UploadSecurityService", lambda: service)
    upload = _file()
    result = await public_security._validated_upload_file(
        upload, label="passport", public_device_file=True,
    )
    assert result == "normalized"
    service.validate_public_file.assert_awaited_once()
    service.validate_image.assert_not_awaited()
    assert upload.file.closed


@pytest.mark.parametrize("session_id", ["a" * 40, None])
def test_prepare_uses_separate_rate_limits_and_requires_session(test_settings, session_id):
    middleware = RateLimitMiddleware(FastAPI(), settings=test_settings, initialize_redis=False)
    request = Request({
        "type": "http", "method": "POST", "path": "/api/v1/passports/upload/synthetic-link/prepare-file",
        "headers": [(b"x-upload-session-id", session_id.encode())] if session_id else [],
        "client": ("203.0.113.10", 50000), "scheme": "http", "server": ("test", 80), "query_string": b"",
    })
    guards, _distributed, error = middleware._guards_for(request)
    if session_id:
        assert error is None
        assert {guard.scope for guard in guards} == {"public-upload-prepare-session", "public-upload-prepare-aggregate"}
        assert [guard.limit for guard in guards] == [30, 600]
    else:
        assert error == "UPLOAD_SESSION_ID_REQUIRED"


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH"])
def test_prepare_budget_covers_malformed_requests_without_spending_submit_quota(test_settings, method):
    middleware = RateLimitMiddleware(FastAPI(), settings=test_settings, initialize_redis=False)
    scope = {
        "type": "http", "method": method,
        "path": "/api/v1/passports/upload/synthetic-link/prepare-file",
        "headers": [(b"x-upload-session-id", b"a" * 40)],
        "client": ("203.0.113.10", 50000), "scheme": "http", "server": ("test", 80), "query_string": b"",
    }
    prepare_guards, _, prepare_error = middleware._guards_for(Request(scope))
    submit_guards, _, submit_error = middleware._guards_for(Request({
        **scope, "method": "POST", "path": "/api/v1/passports/upload/synthetic-link",
    }))
    assert prepare_error is None and submit_error is None
    assert prepare_guards[0].identifier == submit_guards[0].identifier
    assert {guard.scope for guard in prepare_guards}.isdisjoint({guard.scope for guard in submit_guards})
    assert submit_guards[0].limit == 6


def test_production_proxy_routes_preparation_before_small_followup_body_limit():
    root = Path(__file__).resolve().parents[4]
    site = (root / "nginx/conf.d/default.conf").read_text(encoding="utf-8")
    main = (root / "nginx/nginx.conf").read_text(encoding="utf-8")
    preparation = "location ~ ^/api/v1/passports/upload/[^/]+/prepare-file/?$"
    followup = "location ~ ^/api/v1/passports/upload/[^/]+/[^/]+(?:/.*)?/?$"
    assert site.index(preparation) < site.index(followup)
    block = site[site.index(preparation):site.index(followup)]
    assert "client_max_body_size 11M" in block
    assert "zone=upload_prepare_session" in block
    assert "zone=upload_prepare_aggregate" in block
    assert "zone=upload_session " not in block
    assert "zone=upload_prepare_session:10m rate=30r/m" in main
    assert "zone=upload_prepare_aggregate:10m rate=600r/m" in main
