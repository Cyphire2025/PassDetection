"""Run the actual legacy welcome migration against isolated PostgreSQL tables."""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1",
        reason="requires isolated PostgreSQL test service",
    ),
]


async def test_legacy_backfill_requires_current_batch_and_preserves_confirmed_phone_delivery():
    url = URL.create(
        "postgresql+asyncpg",
        username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        database=os.environ["POSTGRES_DB"],
    )
    engine = create_async_engine(url, poolclass=NullPool)
    schema = f"welcome_migration_{uuid.uuid4().hex}"
    path = Path(__file__).resolve().parents[2] / "alembic/versions/0093_phone_welcome.py"
    spec = importlib.util.spec_from_file_location("phone_welcome_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            for table in ("agencies", "users", "client_groups", "whatsapp_broadcast_groups"):
                await connection.execute(text(f"CREATE TABLE {table} (id uuid PRIMARY KEY)"))
            await connection.execute(
                text("""CREATE TABLE whatsapp_broadcast_recipients (
                id uuid PRIMARY KEY, agency_id uuid NOT NULL, normalized_phone_number varchar(32) NOT NULL)""")
            )
            await connection.execute(
                text("""CREATE TABLE whatsapp_message_logs (
                id uuid PRIMARY KEY, agency_id uuid NOT NULL, recipient_id uuid NOT NULL,
                batch_id uuid, message_type varchar(64), status varchar(32),
                provider_status_at timestamptz, status_updated_at timestamptz, created_at timestamptz)""")
            )
            await connection.execute(
                text("""CREATE TABLE whatsapp_recipient_message_states (
                id uuid PRIMARY KEY, agency_id uuid NOT NULL, recipient_id uuid NOT NULL,
                batch_id uuid, message_type varchar(64), status varchar(32))""")
            )
            agency = uuid.uuid4()
            await connection.execute(text("INSERT INTO agencies (id) VALUES (:id)"), {"id": agency})
            log_ids = []
            for index, (log_status, state_batch_matches, null_state_batch) in enumerate(
                [
                    ("delivered", True, False),
                    ("delivered", False, True),
                    ("delivered", False, False),
                    ("sent", True, False),
                ]
            ):
                recipient, batch, log_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
                log_ids.append(log_id)
                phone = f"+9198765432{index:02}"
                await connection.execute(
                    text("INSERT INTO whatsapp_broadcast_recipients VALUES (:id,:agency,:phone)"),
                    {"id": recipient, "agency": agency, "phone": phone},
                )
                await connection.execute(
                    text("""INSERT INTO whatsapp_message_logs
                    VALUES (:id,:agency,:recipient,:batch,'welcome',:status,now(),now(),now())"""),
                    {
                        "id": log_id,
                        "agency": agency,
                        "recipient": recipient,
                        "batch": batch,
                        "status": log_status,
                    },
                )
                state_batch = (
                    None if null_state_batch else batch if state_batch_matches else uuid.uuid4()
                )
                await connection.execute(
                    text("""INSERT INTO whatsapp_recipient_message_states
                    VALUES (:id,:agency,:recipient,:batch,'welcome','delivered')"""),
                    {
                        "id": uuid.uuid4(),
                        "agency": agency,
                        "recipient": recipient,
                        "batch": state_batch,
                    },
                )

            def upgrade(sync_connection):
                migration.op = Operations(MigrationContext.configure(sync_connection))
                migration.upgrade()

            await connection.run_sync(upgrade)
            states = dict(
                (
                    await connection.execute(
                        text(
                            "SELECT normalized_phone_number,status FROM whatsapp_phone_welcomes ORDER BY normalized_phone_number"
                        )
                    )
                ).all()
            )
            assert states == {"+919876543200": "delivered", "+919876543203": "sent"}
            snapshots = dict(
                (
                    await connection.execute(
                        text("SELECT id,normalized_phone_number FROM whatsapp_message_logs")
                    )
                ).all()
            )
            assert snapshots[log_ids[0]] == "+919876543200"
            assert snapshots[log_ids[1]] is None
            assert snapshots[log_ids[2]] is None
            assert snapshots[log_ids[3]] == "+919876543203"
            migration.downgrade  # Downgrade is separately executed against the same transaction.

            def downgrade(sync_connection):
                migration.op = Operations(MigrationContext.configure(sync_connection))
                migration.downgrade()

            await connection.run_sync(downgrade)
            assert (
                await connection.scalar(text("SELECT to_regclass('whatsapp_phone_welcomes')"))
                is None
            )
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()
