"""Exercise the installed sender against an isolated PostgreSQL fixture, never a provider.

The host supplies an internal-only network, synthetic credentials and a 1 GiB
container. The application comes from the exact image; only this fixture is mounted.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, "/app")


async def exercise() -> dict:
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config.settings import get_settings
    from app.infrastructure.database import model_registry  # noqa: F401
    from app.infrastructure.database.models import (
        AgencyModel,
        ClientGroupModel,
        ClientGroupWhatsAppBroadcastLinkModel,
        DistributedDocumentModel,
        DocumentDistributionBatchModel,
        DocumentWhatsAppDeliveryModel,
        PassportSubmissionModel,
        WhatsAppBroadcastGroupModel,
        WhatsAppBroadcastRecipientModel,
    )
    from app.infrastructure.whatsapp import document_delivery_runtime as runtime

    settings = get_settings()
    engine = create_async_engine(settings.database.async_url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now, phone = datetime.now(UTC), "+919999999999"
    agency = AgencyModel(id=uuid.uuid4(), name="Synthetic sender qualification", email="sender@example.test")
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Synthetic trip",
        token=uuid.uuid4().hex, status="active", departure_cities=[])
    broadcast = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Synthetic audience",
        organizing_company_name="Synthetic", recipient_opt_in_confirmed_at=now)
    recipient = WhatsAppBroadcastRecipientModel(id=uuid.uuid4(), agency_id=agency.id,
        broadcast_group_id=broadcast.id, name="Synthetic contact", phone_number=phone,
        normalized_phone_number=phone, imported_fields={})
    passenger = PassportSubmissionModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        client_name="Synthetic passenger", client_phone=phone, family_head_phone=phone,
        image_s3_key="synthetic/passport.jpg", status="confirmed",
        confirmed_fields={}, extracted_fields={}, staff_metadata={})
    link = ClientGroupWhatsAppBroadcastLinkModel(id=uuid.uuid4(), agency_id=agency.id,
        client_group_id=group.id, broadcast_group_id=broadcast.id)
    batch = DocumentDistributionBatchModel(id=uuid.uuid4(), agency_id=agency.id,
        group_id=group.id, document_type="visa", status="saved")
    send_batch = uuid.uuid4()
    async with factory() as session:
        for records in ([agency], [group, broadcast], [recipient, passenger, link, batch]):
            session.add_all(records)
            await session.flush()
        documents, deliveries = [], []
        for index in range(700):
            document = DistributedDocumentModel(id=uuid.uuid4(), batch_id=batch.id,
                agency_id=agency.id, group_id=group.id, passenger_id=passenger.id,
                document_type="visa", original_filename=f"synthetic-{index}.pdf",
                storage_key=f"synthetic/{index}.pdf", match_status="matched")
            documents.append(document)
            deliveries.append(DocumentWhatsAppDeliveryModel(id=uuid.uuid4(), agency_id=agency.id,
                group_id=group.id, passenger_id=passenger.id, broadcast_group_id=broadcast.id,
                recipient_id=recipient.id, send_batch_id=send_batch, document_batch_id=batch.id,
                distributed_document_id=document.id, document_type="visa", document_filename=document.original_filename,
                passenger_name=passenger.client_name, phone_number=phone, normalized_phone_number=phone,
                template_name="documents_v1", template_parameter_values=["Synthetic", "Never send externally"],
                status="delivery_unknown" if index == 0 else "submitted" if index == 1 else "queued",
                attempt_count=0, status_updated_at=now, created_at=now + timedelta(microseconds=index), updated_at=now))
        session.add_all(documents)
        await session.flush()
        session.add_all(deliveries)
        await session.commit()

    active, peak_active, uploads, sends = 0, 0, 0, 0
    upload_barrier = asyncio.Event()

    async def storage_read(_key):
        # Allocate a separate 25 MiB byte buffer for each in-flight document.
        return b"%PDF-1.7\n" + bytes(25 * 1024**2 - 9)

    async def upload(**kwargs):
        nonlocal active, peak_active, uploads
        active += 1
        peak_active = max(peak_active, active)
        try:
            # One additional copy represents request serialization; no HTTP call.
            serialized = bytearray(kwargs["file_content"])
            hashlib.sha256(serialized).digest()
            if active == 4:
                upload_barrier.set()
            await asyncio.wait_for(upload_barrier.wait(), timeout=30)
            await asyncio.sleep(.01)
            uploads += 1
            return f"synthetic-media-{uploads}"
        finally:
            active -= 1

    async def send(**_kwargs):
        nonlocal sends
        sends += 1
        return f"wamid.synthetic.{sends}"

    sizes = []
    try:
        with patch.object(runtime, "AsyncSessionFactory", factory), \
             patch.object(runtime, "get_settings", lambda: SimpleNamespace(whatsapp_delivery_concurrency=4,
                 whatsapp_phone_number_id="synthetic-only")), \
             patch.object(runtime, "MinioStorageRepository", lambda: SimpleNamespace(get_file=storage_read)), \
             patch.object(runtime, "upload_whatsapp_document", upload), \
             patch.object(runtime, "send_whatsapp_document_template", send), \
             patch.object(runtime, "_propagate_first_released_document_batch", AsyncMock(return_value=0)):
            while True:
                previous = sends
                delay = await runtime.run_document_whatsapp_broadcast(send_batch_id=str(send_batch))
                sizes.append(sends - previous)
                if sizes[-1] > 25 or len(sizes) > 28:
                    raise RuntimeError("sender_slice_bound_failed")
                if not delay:
                    break
            if await runtime.run_document_whatsapp_broadcast(send_batch_id=str(send_batch)):
                raise RuntimeError("completed_batch_requeued")
        async with factory() as session:
            counts = dict((await session.execute(select(DocumentWhatsAppDeliveryModel.status,
                func.count()).group_by(DocumentWhatsAppDeliveryModel.status))).all())
        if counts != {"submitted": 699, "delivery_unknown": 1} or sends != uploads or sends != 698 or len(sizes) != 28:
            raise RuntimeError("sender_outcomes_or_duplicate_suppression_failed")
        if peak_active != 4:
            raise RuntimeError("sender_upload_concurrency_failed")
        return {"passed": True, "rows": 700, "slices": sizes, "mock_sends": sends, "mock_uploads": uploads,
            "peak_upload_concurrency": peak_active, "provider_calls": 0, "outcomes": counts,
            "pdf_buffer_bytes_each": 25 * 1024**2,
            "limitations": ["Synthetic storage and provider; no external HTTP or delivery latency qualification."]}
    finally:
        await engine.dispose()


def child(writer) -> None:
    try:
        writer.send(asyncio.run(exercise()))
    finally:
        writer.close()


def main() -> None:
    if os.environ.get("DOCUMENT_RESOURCE_PROBE") != "synthetic-isolated":
        raise RuntimeError("isolated_probe_marker_required")
    if os.environ.get("POSTGRES_DB") != "document_sender_qualification":
        raise RuntimeError("synthetic_database_required")
    from alembic import command
    from alembic.config import Config

    config = Config("/app/alembic.ini")
    config.set_main_option("script_location", "/app/alembic")
    command.upgrade(config, "0140_document_update_context")
    from app.infrastructure.processing.celery_app import celery_app

    celery_app.loader.import_default_modules()
    context = multiprocessing.get_context("fork")
    reader, writer = context.Pipe(duplex=False)
    process = context.Process(target=child, args=(writer,))
    process.start()
    writer.close()
    try:
        if not reader.poll(600):
            raise RuntimeError("synthetic_sender_exceeded_ten_minutes")
        result = reader.recv()
        process.join(10)
        if process.is_alive() or process.exitcode != 0:
            raise RuntimeError("synthetic_sender_child_did_not_finish")
    finally:
        reader.close()
        if process.is_alive():
            process.terminate()
            process.join(10)
        if process.is_alive():
            process.kill()
            process.join(10)
    result["worker_children"] = 1
    result["celery_parent_imported"] = True
    root = Path("/sys/fs/cgroup")
    result["memory"] = {"peak_bytes": int((root / "memory.peak").read_text()),
        "events": dict(line.split() for line in (root / "memory.events").read_text().splitlines())}
    if any(int(result["memory"]["events"].get(key, 0)) for key in ("oom", "oom_kill", "max")):
        raise RuntimeError("sender_memory_limit_reached")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
