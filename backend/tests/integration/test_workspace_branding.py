"""Branding persists through real transactions and never bypasses owner scope."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from PIL import Image, PngImagePlugin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.database.models import ClientGroupModel, StorageCleanupJobModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.upload_validator import (
    DisabledMalwareScanner,
    MalwareScannerUnavailableError,
    UploadValidator,
)
from app.infrastructure.storage.branding_urls import image_version
from app.presentation.api.v1.branding_metadata import group_branding_metadata
from app.presentation.api.v1.routes import branding_images
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.middleware.error_handler import register_exception_handlers
from tests.integration.test_company_directory import company, legacy_group, seed_user


def image_bytes() -> bytes:
    output = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("comment", "untrusted-metadata-marker")
    with Image.new("RGBA", (1280, 400), (12, 100, 170, 180)) as image:
        image.save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()


@pytest.fixture
def storage(monkeypatch):
    class Storage:
        objects = {}
        fail = False

        async def upload_file(self, content, key, content_type):
            if self.fail:
                raise StorageError("Synthetic storage outage")
            self.objects[key] = content
            assert content_type == "image/jpeg"
            return key

        async def get_file(self, key):
            return self.objects[key]

    class Security:
        async def validate_image(self, *, content, filename, declared_content_type, max_dimension,
                                 allowed_source_formats, **kwargs):
            # Exercise the real byte sniffing, bounded decoder and sanitizer;
            # only external malware scanning/evidence storage are substituted.
            return await asyncio.to_thread(UploadValidator(scanner=DisabledMalwareScanner()).validate,
                content=content, filename=filename, declared_content_type=declared_content_type,
                max_dimension=max_dimension, allowed_source_formats=allowed_source_formats)

    target = Storage()
    monkeypatch.setattr(branding_images, "MinioStorageRepository", lambda: target)
    monkeypatch.setattr(branding_images, "UploadSecurityService", Security)
    return target


def application(session_factory, user):
    app = FastAPI()
    app.include_router(branding_images.router, prefix="/api/v1/branding")
    register_exception_handlers(app)

    async def transaction():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = transaction
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[require_cookie_csrf] = lambda: None
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["company-logo", "group-banner"])
async def test_upload_replace_preview_remove_and_tenant_boundaries(db_session, storage, kind):
    user, other = await seed_user(db_session), await seed_user(db_session)
    client_company = await company(db_session, user)
    group = await legacy_group(db_session, user)
    model = await db_session.get(ClientGroupModel, group.id)
    model.company_id = client_company.id
    await db_session.commit()
    owner_id = client_company.id if kind == "company-logo" else group.id
    path = f"/api/v1/branding/{kind}/{owner_id}"
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        uploaded = await http.put(path, files={"file": ("image.png", image_bytes(), "image/png")})
        assert uploaded.status_code == 200, uploaded.text
        url = uploaded.json()["url"]
        assert url and "branding/" not in url.split("?", 1)[-1]
        preview = await http.get(url)
        assert preview.status_code == 200 and preview.headers["cache-control"] == "private, no-store"
        assert b"untrusted-metadata-marker" not in preview.content
        with Image.open(BytesIO(preview.content)) as image:
            assert image.format == "JPEG" and max(image.size) <= (1024 if kind == "company-logo" else 2560)
        async with factory() as session:
            metadata = (await group_branding_metadata(session, [group.id]))[group.id]
            assert metadata["company_logo_url" if kind == "company-logo" else "banner_url"] == url
            assert not list(await session.scalars(select(StorageCleanupJobModel)))
        app.dependency_overrides[get_current_active_user] = lambda: other
        assert (await http.get(url)).status_code in {403, 404}
        assert (await http.put(path, files={"file": ("image.png", image_bytes(), "image/png")})).status_code in {403, 404}
        app.dependency_overrides[get_current_active_user] = lambda: replace(user,
            role=UserRole.AGENCY_STAFF if kind == "company-logo" else UserRole.AGENCY_COORDINATOR)
        assert (await http.put(path, files={"file": ("image.png", image_bytes(), "image/png")})).status_code == 403
        app.dependency_overrides[get_current_active_user] = lambda: user
        stale = await http.put(path, files={"file": ("image.png", image_bytes(), "image/png")})
        assert stale.status_code == 409 and len(storage.objects) == 1
        replacement = await http.put(path, data={"expected_version": image_version(url.split("v=")[-1])},
            files={"file": ("replacement.png", image_bytes(), "image/png")})
        assert replacement.status_code == 200, replacement.text
        new_url = replacement.json()["url"]
        assert new_url != url and (await http.get(url)).status_code == 404
        removed = await http.delete(path, params={"expected_version": new_url.split("v=")[-1]})
        assert removed.status_code == 200 and removed.json()["url"] is None
        assert (await http.get(new_url)).status_code == 404
    async with factory() as session:
        jobs = list(await session.scalars(select(StorageCleanupJobModel)))
        assert len(jobs) == 2 and all(job.source == "branding_image" for job in jobs)


@pytest.mark.asyncio
async def test_failed_upload_leaves_existing_image_and_durable_compensation(db_session, storage, monkeypatch):
    user = await seed_user(db_session)
    item = await company(db_session, user)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user)
    path = f"/api/v1/branding/company-logo/{item.id}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        invalid = await http.put(path, files={"file": ("fake.png", b"<svg>fake</svg>", "image/png")})
        assert 400 <= invalid.status_code < 500 and not storage.objects
        uploaded = await http.put(path, files={"file": ("logo.png", image_bytes(), "image/png")})
        url = uploaded.json()["url"]
        security = branding_images.UploadSecurityService
        monkeypatch.setattr(branding_images, "UploadSecurityService", lambda: SimpleNamespace(
            validate_image=AsyncMock(side_effect=MalwareScannerUnavailableError("Synthetic scanner outage"))))
        unavailable = await http.put(path, data={"expected_version": url.split("v=")[-1]},
            files={"file": ("new.png", image_bytes(), "image/png")})
        assert unavailable.status_code == 503 and unavailable.headers["retry-after"] == "30"
        assert (await http.get(url)).status_code == 200
        monkeypatch.setattr(branding_images, "UploadSecurityService", security)
        storage.fail = True
        failed = await http.put(path, data={"expected_version": url.split("v=")[-1]},
            files={"file": ("new.png", image_bytes(), "image/png")})
        assert failed.status_code >= 500
        assert (await http.get(url)).status_code == 200
    async with factory() as session:
        jobs = list(await session.scalars(select(StorageCleanupJobModel)))
        assert len(jobs) == 1 and jobs[0].status == "pending" and jobs[0].object_count == 1
