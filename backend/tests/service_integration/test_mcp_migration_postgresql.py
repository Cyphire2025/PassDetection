"""Exercise the candidate migration against retained business rows on isolated PostgreSQL."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import URL, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.infrastructure.database.gc_mobile_models import MobileNotificationModel
from app.infrastructure.database.gc_notification_models import (
    GCNotificationBatchModel,
    GCNotificationDraftModel,
    GCNotificationRecipientModel,
)
from app.infrastructure.database.mcp_contact_import_models import MCPContactImportUploadModel
from app.infrastructure.database.mcp_gc_push_models import MCPGCPushOriginModel, MCPGCPushPlanModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.mcp_whatsapp_media_models import (
    MCPWhatsAppHeaderAccessModel,
    MCPWhatsAppHeaderMediaModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.whatsapp_send_intent_models import WhatsAppSendIntentModel
from app.presentation.api.v1.routes.mcp_admin_files import file_projection

pytestmark = [pytest.mark.service_integration, pytest.mark.skipif(
    os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required")]
EXPECTED_HEAD = json.loads((Path(__file__).resolve().parents[2] / "app/core/config/release_manifest.json").read_text())["schema_revision"]


async def test_additive_upgrade_preserves_rows_and_refuses_loss_of_connection_history():
    host = os.environ.get("POSTGRES_HOST", "localhost")
    source = os.environ["POSTGRES_DB"]
    if host not in {"localhost", "127.0.0.1", "postgres", "db"} or (
        source != "test_db" and not source.startswith("passdetection_ci_")):
        pytest.fail("Migration proof requires an isolated local/CI PostgreSQL cluster")
    name = "passdetection_ci_mcp_migration_" + uuid.uuid4().hex[:12]
    base_url = URL.create("postgresql+asyncpg", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=host,
        port=int(os.environ.get("POSTGRES_PORT", "5432")), database=source)
    admin = create_async_engine(base_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    engine = create_async_engine(base_url.set(database=name), poolclass=NullPool)
    environment = {**os.environ, "POSTGRES_DB": name}
    backend = Path(__file__).resolve().parents[2]

    async def migrate(*arguments):
        process = await asyncio.create_subprocess_exec(sys.executable, "-m", "alembic", *arguments,
            cwd=backend, env=environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        output, _ = await asyncio.wait_for(process.communicate(), 90)
        return process.returncode, output.decode("utf-8", errors="replace")

    async def snapshot():
        result = {}
        async with engine.connect() as connection:
            for table in ("agencies", "users", "client_groups", "passport_submissions"):
                records = (await connection.execute(text(
                    f"SELECT row_to_json(record) FROM (SELECT * FROM {table} ORDER BY id) record"
                ))).scalars().all()
                result[table] = json.dumps(records, sort_keys=True)
        return result

    async with admin.connect() as connection:
        # Generated identifier contains only a fixed prefix and hexadecimal UUID.
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        code, output = await migrate("upgrade", "0113_document_follow_up")
        assert code == 0, output[-4000:]
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            agency = AgencyModel(id=uuid.uuid4(), name="Retained agency", email="retained@example.test")
            user = UserModel(id=uuid.uuid4(), email="retained-user@example.test", full_name="Retained user",
                             hashed_password="synthetic", role="super_admin", is_active=True)
            session.add_all([agency, user])
            await session.flush()
            group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Retained group", token=uuid.uuid4().hex)
            session.add(group)
            await session.flush()
            session.add(PassportSubmissionModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
                client_name="Retained passport", image_s3_key="synthetic/retained-source", status="confirmed"))
            await session.commit()
            user_id = user.id
        before = await snapshot()
        # A competing writer fence must stop the upgrade within its declared
        # lock timeout, retain the source version, and permit a clean retry.
        async with engine.begin() as held:
            await held.execute(text("LOCK TABLE users IN ACCESS EXCLUSIVE MODE"))
            code, output = await migrate("upgrade", "head")
            assert code != 0 and "lock timeout" in output
            assert await held.scalar(text("SELECT version_num FROM alembic_version")) == "0113_document_follow_up"
            assert await held.scalar(text("SELECT to_regclass('public.mcp_control')")) is None
        assert await snapshot() == before
        code, output = await migrate("upgrade", "head")
        assert code == 0, output[-4000:]
        assert await snapshot() == before
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT enabled FROM mcp_control WHERE id=1")) is False
            for table in ("mcp_grants", "mcp_authorization_codes", "mcp_tokens", "mcp_operations", "mcp_artifacts", "mcp_artifact_access", "mcp_record_revisions", "mcp_whatsapp_plans", "mcp_whatsapp_outbox", "mcp_contact_import_uploads", "mcp_whatsapp_header_media", "mcp_whatsapp_header_access", "whatsapp_send_intents", "mcp_gc_push_plans", "mcp_gc_push_origins"):
                assert await connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
        code, output = await migrate("downgrade", "0113_document_follow_up")
        assert code == 0, output[-4000:]
        assert await snapshot() == before
        code, output = await migrate("upgrade", "0114_mcp_connections")
        assert code == 0, output[-4000:]
        grant_id, artifact_id = uuid.uuid4(), uuid.uuid4()
        async with factory() as session:
            now = datetime.now(UTC)
            session.add(MCPGrantModel(id=grant_id, user_id=user_id,
                client_id="global-connects-desktop", name="Retained connection", resource="http://localhost:8000/mcp",
                capabilities=["mcp:read"], security_version=1, mfa_at=now, created_at=now, expires_at=now + timedelta(days=7)))
            await session.flush()
            await session.execute(text("""
                INSERT INTO mcp_artifacts (id, handle_hash, user_id, grant_id, agency_id, group_id,
                    direction, purpose, storage_key, filename, media_type, byte_size, sha256, created_at, expires_at)
                VALUES (:id, :handle_hash, :user_id, :grant_id, :agency_id, :group_id,
                    'export', 'passport_excel', 'synthetic/legacy-export', 'legacy.xlsx',
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 3, :sha256, :now, :expiry)
            """), {"id": artifact_id, "handle_hash": "a" * 64, "user_id": user_id,
                "grant_id": grant_id, "agency_id": agency.id, "group_id": group.id,
                "sha256": "b" * 64, "now": now, "expiry": now + timedelta(hours=1)})
            await session.commit()
        code, output = await migrate("upgrade", "head")
        assert code == 0, output[-4000:]
        async with engine.connect() as connection:
            access = (await connection.execute(text("SELECT * FROM mcp_artifact_access"))).mappings().one()
            assert (access["artifact_id"], access["grant_id"], access["handle_hash"], access["handle_version"]) == (
                artifact_id, grant_id, "a" * 64, 0)
            assert await connection.scalar(text("SELECT association_groups FROM mcp_artifacts")) == [
                {"agency_id": str(agency.id), "group_id": str(group.id)}]
        assert await snapshot() == before
        # A legacy-only backfill is reversible without losing its original locator.
        code, output = await migrate("downgrade", "0114_mcp_connections")
        assert code == 0, output[-4000:]
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT handle_hash FROM mcp_artifacts")) == "a" * 64
        code, output = await migrate("upgrade", "head")
        assert code == 0, output[-4000:]
        async with engine.begin() as connection:
            await connection.execute(text("UPDATE mcp_artifact_access SET handle_version = 1"))
        code, output = await migrate("downgrade", "0114_mcp_connections")
        assert code != 0 and "workflow history must be retained" in output
        async with engine.begin() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_HEAD
            assert await connection.scalar(text("SELECT handle_version FROM mcp_artifact_access")) == 1
            await connection.execute(text("UPDATE mcp_artifact_access SET handle_version = 0"))
        code, output = await migrate("downgrade", "0113_document_follow_up")
        assert code != 0 and "connection history must be retained" in output
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_HEAD
            assert await connection.scalar(text("SELECT count(*) FROM mcp_grants")) == 1
        assert await snapshot() == before
        # An orphaned dispatch origin must survive even when its former plan is gone.
        async with engine.begin() as connection:
            await connection.execute(text("""
                INSERT INTO mcp_whatsapp_outbox (id, plan_id, batch_id, status, publication_attempts,
                    next_attempt_at, created_at, updated_at)
                VALUES (:id, NULL, :batch_id, 'blocked', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """), {"id": uuid.uuid4(), "batch_id": uuid.uuid4()})
        code, output = await migrate("downgrade", "0116_mcp_communications")
        assert code != 0 and "dispatch origins must be retained" in output
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_HEAD
            assert await connection.scalar(text("SELECT count(*) FROM mcp_whatsapp_outbox WHERE plan_id IS NULL")) == 1
        operation_id = uuid.uuid4()
        async with factory() as session:
            session.add(MCPOperationModel(id=operation_id, user_id=user_id, initial_grant_id=grant_id,
                operation_name="synthetic_ingestion", capability="mcp:upload", idempotency_hash="c" * 64,
                payload_hash="d" * 64, workflow_id=uuid.uuid4(), status="queued", progress=0,
                stage="queued", initial_result={"retained": True}))
            await session.flush()
            await session.execute(text("UPDATE mcp_artifacts SET ingestion_operation_id=:id"), {"id": operation_id})
            await session.commit()
        code, output = await migrate("downgrade", "0117_mcp_dispatch_origin")
        assert code != 0 and "ingestion history must be retained" in output
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_HEAD
            assert await connection.scalar(text("SELECT ingestion_operation_id FROM mcp_artifacts")) == operation_id
        async with factory() as session:
            session.add(MCPContactImportUploadModel(id=uuid.uuid4(), user_id=user_id, original_grant_id=grant_id,
                agency_id=agency.id, handle_hash="e" * 64, storage_key="synthetic/retained-contact-upload",
                filename="contacts.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                byte_size=3, sha256="f" * 64, workbook_snapshot={"schema": 1, "sheets": []},
                created_at=now, expires_at=now + timedelta(hours=1)))
            await session.commit()
        code, output = await migrate("downgrade", "0118_mcp_pdf_ingestion")
        assert code != 0 and "contact source history must be retained" in output
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_HEAD
            assert await connection.scalar(text("SELECT count(*) FROM mcp_contact_import_uploads")) == 1
        media_id = uuid.uuid4()
        async with factory() as session:
            broadcast = WhatsAppBroadcastGroupModel(agency_id=agency.id, name="Retained media scope")
            session.add(broadcast)
            await session.flush()
            session.add(MCPWhatsAppHeaderMediaModel(id=media_id, user_id=user_id, original_grant_id=grant_id,
                agency_id=agency.id, broadcast_id=broadcast.id, idempotency_hash="1" * 64, request_hash="2" * 64,
                handle_hash="3" * 64, original_storage_key="synthetic/retained-media-source",
                normalized_storage_key="synthetic/retained-media-normalized", original_sha256="4" * 64,
                normalized_sha256="5" * 64, original_byte_size=3, normalized_byte_size=3,
                filename="header.png", original_media_type="image/png", normalized_media_type="image/png",
                provider_phone_number_id="synthetic-provider", status="staged", created_at=now,
                updated_at=now, expires_at=now + timedelta(hours=1)))
            await session.flush()
            session.add(MCPWhatsAppHeaderAccessModel(media_id=media_id, grant_id=grant_id,
                handle_hash="6" * 64, created_at=now))
            await session.commit()
        # SQL CHECK must reject an incomplete attempt even under SQL NULL semantics.
        with pytest.raises(IntegrityError, match="ck_mcp_wa_media_attempt"):
            async with engine.begin() as connection:
                await connection.execute(text("UPDATE mcp_whatsapp_header_media SET attempt_id=:attempt, attempted_at=CURRENT_TIMESTAMP WHERE id=:id"),
                    {"attempt": uuid.uuid4(), "id": media_id})
        code, output = await migrate("downgrade", "0119_mcp_contact_imports")
        assert code != 0 and "WhatsApp media history must be retained" in output
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_HEAD
            assert await connection.scalar(text("SELECT count(*) FROM mcp_whatsapp_header_media")) == 1
            assert await connection.scalar(text("SELECT count(*) FROM mcp_whatsapp_header_access")) == 1
            projection = file_projection(now)
            media = (await connection.execute(select(projection).where(projection.c.kind == "whatsapp_header"))).mappings().one()
            assert media["id"] == media_id and media["status"] == "staged"
            assert media["group_id"] is None and media["broadcast_id"] is not None
        async with factory() as session:
            session.add(WhatsAppSendIntentModel(user_id=user_id, agency_id=agency.id,
                broadcast_id=broadcast.id, idempotency_hash="7" * 64, request_hash="8" * 64,
                initial_response={"queued": 0}, worker_payload={}, publication_status="no_batch",
                publication_attempts=0, next_attempt_at=now, created_at=now, updated_at=now))
            await session.commit()
        code, output = await migrate("downgrade", "0120_mcp_whatsapp_media")
        assert code != 0 and "send intent history must be retained" in output
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_HEAD
            assert await connection.scalar(text("SELECT count(*) FROM whatsapp_send_intents")) == 1
        # A retained origin without its former plan still prohibits downgrade.
        async with factory() as session:
            draft = GCNotificationDraftModel(agency_id=agency.id, title="Retained push",
                body="Synthetic history only", audience="selected_groups", group_ids=[str(group.id)])
            session.add(draft)
            await session.flush()
            batch = GCNotificationBatchModel(agency_id=agency.id, draft_id=draft.id,
                draft_revision=1, request_id=uuid.uuid4(), request_fingerprint="9" * 64,
                title=draft.title, body=draft.body, audience=draft.audience,
                group_ids=[str(group.id)], group_names=["Retained group"], role_counts={"coordinator": 1},
                created_at=now, expires_at=now + timedelta(hours=1))
            session.add(batch)
            await session.flush()
            recipient = GCNotificationRecipientModel(agency_id=agency.id, batch_id=batch.id,
                recipient_type="coordinator", person_key="synthetic-retained-person")
            session.add(recipient)
            await session.flush()
            notification = MobileNotificationModel(agency_id=agency.id, recipient_type="authored",
                authored_recipient_id=recipient.id, notification_type="gc_alert", category="announcement",
                title=draft.title, body=draft.body, dedupe_key=uuid.uuid4().hex)
            session.add(notification)
            await session.flush()
            session.add(MCPGCPushOriginModel(notification_id=notification.id, batch_id=batch.id, plan_id=None))
            await session.commit()
        code, output = await migrate("downgrade", "0121_whatsapp_send_intents")
        assert code != 0 and "GC push history and origins must be retained" in output
        async with factory() as session:
            plan = MCPGCPushPlanModel(operation_id=operation_id, user_id=user_id,
                original_grant_id=grant_id, agency_id=agency.id, draft_id=draft.id,
                snapshot={"retained": True}, snapshot_hash="a" * 64, status="blocked",
                prepared_at=now, expires_at=now + timedelta(minutes=10))
            session.add(plan)
            await session.commit()
        with pytest.raises(IntegrityError, match="ck_mcp_gc_push_plan_hash_alphabet"):
            async with engine.begin() as connection:
                await connection.execute(text("UPDATE mcp_gc_push_plans SET snapshot_hash=:hash"), {"hash": "G" * 64})
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_HEAD
            assert await connection.scalar(text("SELECT count(*) FROM mcp_gc_push_origins WHERE plan_id IS NULL")) == 1
            assert await connection.scalar(text("SELECT snapshot_hash FROM mcp_gc_push_plans")) == "a" * 64
        assert await snapshot() == before
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            # Only this fixture's freshly generated database is removed.
            await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()
