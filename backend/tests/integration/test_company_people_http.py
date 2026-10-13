"""Real staff HTTP boundaries, protected lazy sources and durable downloads."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.traveller_reuse_models import TravellerMatchCaseModel as MatchCase
from app.presentation.api.v1.routes import (
    company_data_exports,
    company_document_uploads,
    company_people,
    company_source_documents,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.middleware.error_handler import register_exception_handlers
from tests.integration.test_company_data_exports import drain, export_fixture
from tests.integration.test_company_people import people_fixture


def application(factory, user, crypto):
    app = FastAPI()
    app.include_router(company_people.router, prefix="/api/v1/companies")
    app.include_router(company_data_exports.router, prefix="/api/v1/companies")
    app.include_router(company_document_uploads.router, prefix="/api/v1/companies")
    register_exception_handlers(app)

    async def transaction():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_session] = transaction
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[require_cookie_csrf] = lambda: None
    app.dependency_overrides[company_people.crypto_dependency] = lambda: crypto
    return app


@pytest.mark.asyncio
async def test_original_sources_are_lazy_private_and_person_scoped(db_session, monkeypatch):
    ctx, person, user = await people_fixture(db_session)
    db_session.add(MatchCase(agency_id=person.agency_id, company_id=person.company_id,
        group_id=ctx.group.id, traveller_id=person.id, source_kind="passport_submission",
        source_row_key=str(ctx.source.id), status="resolved", reason_code="operator_historical_registration"))
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user, ctx.crypto)
    # Listing cannot fetch provider metadata or document bytes.
    monkeypatch.setattr(company_source_documents, "MinioStorageRepository", lambda: pytest.fail("Eager source image I/O"))
    prefix = f"/api/v1/companies/{person.company_id}/people/{person.id}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get(prefix + "/sources")
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "private, no-store"
        item = response.json()["items"][0]
        assert item["id"] == str(ctx.source.id) and item["available_sides"] == ["front", "back"]
        assert "object_key" not in response.text and ctx.source.image_s3_key not in response.text
        missing = await http.get(prefix + f"/sources/{uuid.uuid4()}/assets/front")
        assert missing.status_code == 404
        unsupported = await http.get(prefix + f"/sources/{ctx.source.id}/assets/not-a-side")
        assert unsupported.status_code == 404
        foreign = await http.get(f"/api/v1/companies/{uuid.uuid4()}/people/{person.id}/sources")
        assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_export_download_is_streamed_attachment_private_and_actor_bound(db_session, monkeypatch):
    ctx, person, user, job_id, storage, factory = await export_fixture(db_session)
    await drain(factory, storage, ctx.crypto, job_id)
    app = application(factory, user, ctx.crypto)
    monkeypatch.setattr(company_data_exports, "MinioStorageRepository", lambda: storage)
    prefix = f"/api/v1/companies/{person.company_id}/data-exports/{job_id}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        listed = await http.get(prefix + "/parts")
        assert listed.status_code == 200, listed.text
        assert len(listed.json()["items"]) == 1
        part = listed.json()["items"][0]
        downloaded = await http.get(prefix + f"/parts/{part['id']}/download")
        assert downloaded.status_code == 200
        assert downloaded.headers["Cache-Control"] == "private, no-store"
        assert downloaded.headers["Content-Disposition"].startswith("attachment;")
        assert len(downloaded.content) == part["byte_size"]
        manifest = await http.get(prefix + "/manifest")
        assert manifest.status_code == 200 and manifest.headers["Content-Disposition"].startswith("attachment;")
        assert "object_key" not in manifest.text
        wrong_job = await http.get(prefix.replace(str(job_id), str(uuid.uuid4())) + f"/parts/{part['id']}/download")
        assert wrong_job.status_code == 404
        # Completed bytes remain owned, but a changed current record invalidates
        # subsequent delivery rather than serving an obsolete identity snapshot.
        changed = await http.patch(f"/api/v1/companies/{person.company_id}/people/{person.id}/record",
            json={"expected_revision": 1, "idempotency_key": "invalidate-export", "reason": "Reviewed current change",
                "display_name": "Changed current person"})
        assert changed.status_code == 200, changed.text
        denied = await http.get(prefix + f"/parts/{part['id']}/download")
        assert denied.status_code == 404
        assert storage.objects  # Controlled cleanup owns removal after revocation.


@pytest.mark.asyncio
async def test_lost_image_write_response_keeps_old_current_and_retries_same_version(db_session, monkeypatch):
    from app.application.companies.people import current_person
    from tests.integration.test_company_data_exports import MemoryStorage
    ctx, person, user = await people_fixture(db_session)
    before = await current_person(db_session, person, ctx.crypto)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user, ctx.crypto)
    validator = SimpleNamespace(validate_image=AsyncMock(return_value=SimpleNamespace(content=b"synthetic-image", content_type="image/jpeg")))
    monkeypatch.setattr(company_document_uploads, "UploadSecurityService", lambda: validator)
    storage = MemoryStorage()
    storage.fail_upload = True
    monkeypatch.setattr(company_document_uploads, "MinioStorageRepository", lambda: storage)
    from app.application.companies.people_contracts import DocumentUpload
    metadata = DocumentUpload(expected_revision=1, idempotency_key="lost-provider-response", reason="Reviewed sharper front",
        change_kind="scan", side="front", issuing_country="IND", document_type=before.current_document.document_type,
        fields={key: value for key, value in before.current_document.fields.items() if key != "document_type"}).model_dump_json()
    prefix = f"/api/v1/companies/{person.company_id}/people/{person.id}"
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as http:
        failed = await http.post(prefix + "/documents", data={"metadata": metadata}, files={"file": ("front.jpg", b"synthetic-image", "image/jpeg")})
        assert failed.status_code == 500
        unchanged = (await http.get(prefix + "/record")).json()
        assert unchanged["revision"] == 1 and unchanged["current_document"]["id"] == str(before.current_document.id)
        storage.fail_upload = False
        saved = await http.post(prefix + "/documents", data={"metadata": metadata}, files={"file": ("front.jpg", b"synthetic-image", "image/jpeg")})
        assert saved.status_code == 201, saved.text
        assert saved.json()["revision"] == 2 and saved.json()["current_document"]["revision_number"] == 2
        assert storage.uploads[0] == storage.uploads[1]
        duplicate = await http.post(prefix + "/documents", data={"metadata": metadata}, files={"file": ("front.jpg", b"synthetic-image", "image/jpeg")})
        assert duplicate.status_code == 201 and duplicate.json()["revision"] == 2 and len(storage.uploads) == 2


@pytest.mark.asyncio
async def test_people_and_versions_http_cursors_are_scoped_and_lazy(db_session, monkeypatch):
    from dataclasses import replace

    from app.application.companies.current_record import edit_current_record
    from app.application.companies.people_contracts import PersonEdit
    from app.domain.entities.entities import UserRole
    from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel as Person

    ctx, person, user = await people_fixture(db_session)
    other = Person(agency_id=person.agency_id, company_id=person.company_id, status="active")
    db_session.add(other)
    await db_session.flush()
    db_session.add(MatchCase(agency_id=person.agency_id, company_id=person.company_id,
        group_id=ctx.group.id, traveller_id=other.id, source_kind="passport_submission",
        source_row_key=str(ctx.source.id), status="resolved", reason_code="synthetic"))
    await edit_current_record(db_session, person=person, actor_id=user.id, crypto=ctx.crypto,
        body=PersonEdit(expected_revision=1, idempotency_key="version-page", reason="Reviewed correction",
            display_name="Synthetic Person", fields={"surname": "Correction"}))
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user, ctx.crypto)
    monkeypatch.setattr(company_people, "MinioStorageRepository", lambda: pytest.fail("Eager image I/O"))
    prefix = f"/api/v1/companies/{person.company_id}/people"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        first = await http.get(prefix, params={"page_size": 1})
        assert first.status_code == 200 and first.headers["Cache-Control"] == "private, no-store"
        first_page = first.json()
        assert first_page["has_more"] and first_page["indexing_pending"]
        second = await http.get(prefix, params={"page_size": 1, "cursor": first_page["next_cursor"]})
        assert second.status_code == 200 and not second.json()["has_more"]
        assert {first_page["items"][0]["id"], second.json()["items"][0]["id"]} == {str(person.id), str(other.id)}
        changed_filter = await http.get(prefix, params={"search": "different", "cursor": first_page["next_cursor"]})
        assert changed_filter.status_code == 422
        for search in ("Synthetic Person", str(person.id)):
            searched = await http.get(prefix, params={"search": search})
            assert [row["id"] for row in searched.json()["items"]] == [str(person.id)]
        record = await http.get(prefix + f"/{person.id}/record")
        assert record.status_code == 200 and record.json()["current_document"]["revision_number"] == 2
        versions = await http.get(prefix + f"/{person.id}/documents", params={"page_size": 1})
        assert versions.status_code == 200 and versions.json()["has_more"]
        next_versions = await http.get(prefix + f"/{person.id}/documents",
            params={"page_size": 1, "cursor": versions.json()["next_cursor"]})
        assert next_versions.status_code == 200 and not next_versions.json()["has_more"]
        assert {versions.json()["items"][0]["revision_number"], next_versions.json()["items"][0]["revision_number"]} == {1, 2}
        replay = await http.get(prefix + f"/{other.id}/documents", params={"cursor": versions.json()["next_cursor"]})
        assert replay.status_code == 422
        missing = await http.get(prefix + f"/{uuid.uuid4()}/record")
        assert missing.status_code == 404
        foreign = await http.get(prefix.replace(str(person.company_id), str(uuid.uuid4())))
        assert foreign.status_code == 404
        app.dependency_overrides[get_current_active_user] = lambda: replace(user, role=UserRole.AGENCY_STAFF)
        assert (await http.get(prefix)).status_code == 403


@pytest.mark.asyncio
async def test_withdrawn_unreferenced_retained_image_is_denied_but_trip_copy_remains(db_session, monkeypatch):
    from app.application.companies.export_source import retained_image_page
    from app.infrastructure.database.company_data_export_models import (
        CompanyDataExportJobModel as Job,
    )
    from app.infrastructure.database.traveller_reuse_models import (
        TravellerDocumentAssetModel as Asset,
    )
    from tests.integration.test_company_data_exports import MemoryStorage

    ctx, person, user = await people_fixture(db_session)
    asset = await db_session.scalar(select(Asset).where(Asset.document_side == "front"))
    person.reuse_permission_status = "withdrawn"
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    app = application(factory, user, ctx.crypto)
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (b"0123456789", "image/jpeg")
    monkeypatch.setattr(company_people, "MinioStorageRepository", lambda: storage)
    url = f"/api/v1/companies/{person.company_id}/people/{person.id}/assets/{asset.id}"
    job = Job(agency_id=person.agency_id, company_id=person.company_id, created_at=datetime.now(UTC))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.get(url)).status_code == 404
        assert await retained_image_page(db_session, job, user) == []
        # The original accepted participation preserves its precise lawful trip
        # copy independently of future-reuse permission.
        ctx.source.image_s3_key = asset.object_key
        await db_session.commit()
        allowed = await http.get(url)
        assert allowed.status_code == 200 and allowed.content == b"0123456789"
        assert allowed.headers["Cache-Control"] == "private, no-store"
        assert [image.identifier for image in await retained_image_page(db_session, job, user)] == [asset.id]
        asset.purged_at = datetime.now(UTC)
        await db_session.commit()
        assert (await http.get(url)).status_code == 404
