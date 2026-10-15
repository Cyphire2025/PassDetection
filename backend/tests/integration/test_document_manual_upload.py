"""HTTP + real SQL coverage for explicit passenger uploads and retained replacements."""
from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pypdf import PdfWriter
from sqlalchemy import select

from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents import distribution_ingestion
from app.infrastructure.documents.document_matcher import DocumentMatcher
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.security.upload_security import UploadSecurityService
from app.infrastructure.security.upload_validator import MalwareScanRejectedError
from app.presentation.api.v1 import document_uploads
from app.presentation.api.v1.routes import document_distribution_manual_upload as route
from app.presentation.api.v1.routes import document_distribution_responses as responses
from app.presentation.dependencies.auth import get_current_active_user


class Storage:
    def __init__(self):
        self.objects = {}
        self.deleted = []
        self.after_write = None

    async def upload_file(self, content, key, content_type):
        self.objects[key] = content
        if self.after_write:
            await self.after_write()
        return key

    async def delete_files(self, keys):
        self.deleted.extend(keys)
        for key in keys:
            self.objects.pop(key, None)

    async def get_presigned_url(self, key):
        return f"https://files.example.test/{key}"


class Scanner:
    error = None

    def scan(self, content):
        if self.error:
            raise self.error("test scanner rejection")


def pdf():
    writer, stream = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=100, height=100)
    writer.write(stream)
    return stream.getvalue()


@pytest.fixture
async def manual(db_session, test_settings, monkeypatch):
    agency = AgencyModel(id=uuid.uuid4(), name="Manual upload", email="agency@example.test")
    actor = UserModel(id=uuid.uuid4(), agency_id=agency.id, role="agency_admin", email="admin@example.test",
        hashed_password="unused", full_name="Staff", is_active=True)
    db_session.add(agency)
    await db_session.flush()
    db_session.add(actor)
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Manual group", token=uuid.uuid4().hex)
    db_session.add(group)
    await db_session.flush()
    first, second = [PassportSubmissionModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        client_name="SAME NAME", image_s3_key="test/passport", status="staff_approved") for _ in range(2)]
    db_session.add_all([first, second])
    await db_session.commit()
    actor_entity = await UserRepository(db_session).get_by_id(actor.id)
    storage, scanner = Storage(), Scanner()
    security = UploadSecurityService(settings=test_settings, scanner=scanner, storage=storage)
    monkeypatch.setattr(security, "_record", AsyncMock())
    monkeypatch.setattr(document_uploads, "UploadSecurityService", lambda **_: security)
    monkeypatch.setattr(document_uploads, "malware_scanner_from_settings", lambda: scanner)
    monkeypatch.setattr(document_uploads, "get_settings", lambda: test_settings)
    monkeypatch.setattr(distribution_ingestion, "MinioStorageRepository", lambda: storage)
    monkeypatch.setattr(responses, "MinioStorageRepository", lambda: storage)
    monkeypatch.setattr(route, "_cleanup_distribution_storage_keys", lambda keys, **_: storage.delete_files(keys))
    # SQLite provides transaction tests here; PostgreSQL owns the production
    # advisory-lock implementation (covered by the service integration suite).
    monkeypatch.setattr(route, "acquire_document_upload_scope_advisory_lock", AsyncMock())
    # These expensive matching paths must never run, even for unclassifiable PDFs
    # and identical legal/display names.
    def unexpected(*_args, **_kwargs):
        raise AssertionError("Automatic classification/matching was invoked")
    monkeypatch.setattr(distribution_ingestion, "classify_documents_bounded", unexpected)
    monkeypatch.setattr(DocumentMatcher, "build_index", unexpected)
    monkeypatch.setattr(DocumentMatcher, "match_all", unexpected)
    app = FastAPI()
    app.include_router(route.router)
    async def session():
        yield db_session
    app.dependency_overrides[get_db_session] = session
    app.dependency_overrides[get_current_active_user] = lambda: actor_entity
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield SimpleNamespace(session=db_session, client=client, agency_id=agency.id, actor_id=actor.id,
            group_id=group.id, passenger_id=first.id, other_passenger_id=second.id, storage=storage, scanner=scanner)


async def upload(f, *, lane="visa", passenger_id=None, mode="add", documents=None, content=None):
    return await f.client.post(f"/groups/{f.group_id}/{lane}/passengers/{passenger_id or f.passenger_id}/manual-upload",
        data={"mode": mode, "replacement_documents": json.dumps(documents or [])},
        files={"file": ("manual.pdf", pdf() if content is None else content, "application/pdf")})


@pytest.mark.parametrize("lane", ["visa", "flight_ticket", "flight_ticket_arrival", "flight_ticket_domestic", "flight_ticket_domestic_arrival"])
async def test_manual_upload_saves_only_explicit_passenger_without_matching(manual, lane):
    result = await upload(manual, lane=lane)
    assert result.status_code == 201, result.text
    body = result.json()
    assert body["status"] == "saved"
    rows = {row["passenger_id"]: row for row in body["review_rows"]}
    selected = rows[str(manual.passenger_id)]
    assert len(selected["documents"]) == 1
    assert selected["document"]["manual_type_approved"] is True
    assert selected["document"]["delivery_status"] == "not_sent"
    assert rows[str(manual.other_passenger_id)]["documents"] == []
    assert len(manual.storage.objects) == 1


async def test_manual_replacement_retains_shared_pdf_other_assignment_and_audit_history(manual):
    first = (await upload(manual)).json()["review_rows"]
    old = next(row["document"] for row in first if row["passenger_id"] == str(manual.passenger_id))
    original = await manual.session.get(DistributedDocumentModel, uuid.UUID(old["id"]))
    key, batch_id = original.storage_key, original.batch_id
    other = DistributedDocumentModel(id=uuid.uuid4(), batch_id=batch_id, agency_id=manual.agency_id,
        group_id=manual.group_id, passenger_id=manual.other_passenger_id, document_type="visa",
        original_filename="manual.pdf", storage_key=key, match_status="matched", match_confidence=1)
    manual.session.add(other)
    await manual.session.commit()
    other_id = other.id
    result = await upload(manual, mode="replace", documents=[{"id": old["id"], "updated_at": old["updated_at"]}])
    assert result.status_code == 201, result.text
    old_model = await manual.session.get(DistributedDocumentModel, uuid.UUID(old["id"]))
    assert old_model.match_status == "superseded" and old_model.storage_key == key
    assert (await manual.session.get(DistributedDocumentModel, other_id)).match_status == "matched"
    assert key in manual.storage.objects and not manual.storage.deleted
    rows = {row["passenger_id"]: row for row in result.json()["review_rows"]}
    assert len(rows[str(manual.passenger_id)]["documents"]) == 1
    assert rows[str(manual.passenger_id)]["document"]["id"] != old["id"]
    assert rows[str(manual.other_passenger_id)]["document"]["id"] == str(other_id)
    events = list((await manual.session.scalars(select(AuditLogModel).where(
        AuditLogModel.action == "document_distribution_passenger_document_replaced"))).all())
    assert len(events) == 1


async def test_replacement_rejects_stale_or_other_passenger_version_and_cleans_new_file(manual):
    first = (await upload(manual)).json()["review_rows"]
    old = next(row["document"] for row in first if row["passenger_id"] == str(manual.passenger_id))
    for passenger_id, timestamp in [(manual.passenger_id, datetime.now(UTC).isoformat()),
                                    (manual.other_passenger_id, old["updated_at"])]:
        result = await upload(manual, passenger_id=passenger_id, mode="replace",
            documents=[{"id": old["id"], "updated_at": timestamp}])
        assert result.status_code == 409, result.text
    assert len(manual.storage.objects) == 1
    assert len(manual.storage.deleted) == 2
    assert (await manual.session.get(DistributedDocumentModel, uuid.UUID(old["id"]))).match_status == "matched"


async def test_manual_upload_keeps_security_checks_and_scope_checks(manual):
    invalid = await upload(manual, content=b"not a PDF")
    assert invalid.status_code == 422
    manual.scanner.error = MalwareScanRejectedError
    infected = await upload(manual)
    assert infected.status_code == 422
    missing = await upload(manual, passenger_id=uuid.uuid4())
    assert missing.status_code == 404
    assert not any(key.startswith("document-distribution/") for key in manual.storage.objects)


async def test_manual_upload_revalidates_passenger_after_storage_and_compensates(manual):
    passenger_id = manual.passenger_id
    async def moved():
        passenger = await manual.session.get(PassportSubmissionModel, passenger_id)
        passenger.status = "draft"
        await manual.session.commit()
    manual.storage.after_write = moved
    result = await upload(manual)
    assert result.status_code == 409, result.text
    assert not manual.storage.objects
    assert len(manual.storage.deleted) == 1


async def delivery_for(f, document, status):
    model = await f.session.get(DistributedDocumentModel, uuid.UUID(document["id"]))
    delivery = DocumentWhatsAppDeliveryModel(id=uuid.uuid4(), agency_id=f.agency_id, group_id=f.group_id,
        passenger_id=f.passenger_id, document_batch_id=model.batch_id, distributed_document_id=model.id,
        send_batch_id=uuid.uuid4(), document_type="visa", document_filename=model.original_filename,
        passenger_name="Same Name", phone_number="+919999999999", normalized_phone_number="919999999999",
        template_name="documents_v1", status=status, provider_message_id="test-provider-id" if status == "delivered" else None)
    f.session.add(delivery)
    await f.session.commit()
    return delivery.id


@pytest.mark.parametrize("status", ["queued", "processing", "delivery_unknown"])
async def test_manual_replacement_blocks_inflight_and_unknown_deliveries(manual, status):
    first = (await upload(manual)).json()["review_rows"]
    old = next(row["document"] for row in first if row["passenger_id"] == str(manual.passenger_id))
    delivery_id = await delivery_for(manual, old, status)
    response = await upload(manual, mode="replace", documents=[{"id": old["id"], "updated_at": old["updated_at"]}])
    assert response.status_code == 409, response.text
    assert (await manual.session.get(DocumentWhatsAppDeliveryModel, delivery_id)).status == status
    assert (await manual.session.get(DistributedDocumentModel, uuid.UUID(old["id"]))).match_status == "matched"
    assert len(manual.storage.objects) == 1


async def test_manual_replacement_keeps_past_delivery_and_new_document_is_not_sent(manual):
    first = (await upload(manual)).json()["review_rows"]
    old = next(row["document"] for row in first if row["passenger_id"] == str(manual.passenger_id))
    delivery_id = await delivery_for(manual, old, "delivered")
    response = await upload(manual, mode="replace", documents=[{"id": old["id"], "updated_at": old["updated_at"]}])
    assert response.status_code == 201, response.text
    history = await manual.session.get(DocumentWhatsAppDeliveryModel, delivery_id)
    assert history.status == "delivered" and history.provider_message_id == "test-provider-id"
    assert history.distributed_document_id == uuid.UUID(old["id"])
    current = next(row["document"] for row in response.json()["review_rows"] if row["passenger_id"] == str(manual.passenger_id))
    assert current["delivery_status"] == "not_sent"
    assert len(list((await manual.session.scalars(select(DocumentWhatsAppDeliveryModel))).all())) == 1


async def test_manual_upload_does_not_save_other_drafts_and_rejects_incomplete_uploads(manual):
    batch_id = uuid.uuid4()
    manual.session.add(DocumentDistributionBatchModel(id=batch_id, agency_id=manual.agency_id,
        group_id=manual.group_id, document_type="visa", status="draft"))
    await manual.session.commit()
    response = await upload(manual)
    assert response.status_code == 201, response.text
    batch = await manual.session.get(DocumentDistributionBatchModel, batch_id)
    assert batch.status == "draft" and batch.saved_at is None
    batch.status = "processing"
    await manual.session.commit()
    blocked = await upload(manual)
    assert blocked.status_code == 409, blocked.text
    assert len(manual.storage.objects) == 1
