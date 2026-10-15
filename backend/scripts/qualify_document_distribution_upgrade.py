"""Exercise the additive document columns on a new disposable test database.

This is a qualification harness, not a production migration command. It accepts
only a local explicitly named CI database and creates/removes its own synthetic
database. It never sends a message or connects to an application service.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import URL, create_engine, insert, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.infrastructure.database import model_registry  # noqa: F401 -- load all related mappers
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)

SOURCE = "0138_verified_portal_lookup"
TARGET = "0140_document_update_context"
ROOT = Path(__file__).resolve().parents[1]


def qualify(*, release_helper: bool = False) -> dict[str, object]:
    host, database = os.environ["POSTGRES_HOST"], os.environ["POSTGRES_DB"]
    if host not in {"localhost", "127.0.0.1"} or not database.startswith("passdetection_ci_"):
        raise RuntimeError("Qualification requires an explicitly isolated local CI PostgreSQL database")
    name = "passdetection_ci_doc_update_" + uuid.uuid4().hex[:12]
    url = URL.create("postgresql+psycopg2", username=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=host,
        port=int(os.environ.get("POSTGRES_PORT", "5432")), database=database)
    admin = create_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    engine = create_engine(url.set(database=name), poolclass=NullPool)
    environment = {**os.environ, "POSTGRES_DB": name}
    rows = {}
    created = False

    def migrate(action, target, *, success=True):
        result = subprocess.run([sys.executable, "-m", "alembic", action, target], cwd=ROOT,
            env=environment, text=True, capture_output=True, timeout=180)
        output = result.stdout + result.stderr
        if success:
            assert result.returncode == 0, output[-4000:]
        else:
            assert result.returncode != 0 and "lock timeout" in output, output[-4000:]

    def snapshot():
        with engine.connect() as connection:
            return {table: connection.execute(text(
                f"SELECT to_jsonb(t) - 'display_name' - 'document_update_context' FROM {table} t WHERE id=:id"
            ), {"id": identifier}).scalar_one() for table, identifier in rows.items()}

    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
            created = True
        migrate("upgrade", SOURCE)
        agency, group, passenger, broadcast, recipient, message = [uuid.uuid4() for _ in range(6)]
        now = datetime.now(UTC)
        with engine.begin() as connection:
            connection.execute(insert(AgencyModel.__table__).values(id=agency, name="Synthetic agency", email="synthetic@example.test"))
            connection.execute(insert(ClientGroupModel.__table__).values(id=group, agency_id=agency, name="Synthetic group", token=uuid.uuid4().hex))
            connection.execute(insert(PassportSubmissionModel.__table__).values(id=passenger, group_id=group,
                agency_id=agency, client_name="SYNTHETIC TRAVELLER", client_phone="+919000000001",
                image_s3_key="synthetic/not-stored", status="confirmed",
                confirmed_fields={"passport_number": "P1234567", "full_name": "LEGAL NAME"}))
            connection.execute(insert(WhatsAppBroadcastGroupModel.__table__).values(id=broadcast,
                agency_id=agency, name="Synthetic broadcast", organizing_company_name="Synthetic"))
            connection.execute(insert(WhatsAppBroadcastRecipientModel.__table__).values(id=recipient,
                broadcast_group_id=broadcast, agency_id=agency, name="SYNTHETIC TRAVELLER",
                phone_number="+919000000001", normalized_phone_number="919000000001"))
            connection.execute(insert(WhatsAppMessageLogModel.__table__).values(id=message,
                broadcast_group_id=broadcast, recipient_id=recipient, agency_id=agency,
                message_type="welcome", normalized_phone_number="919000000001", status="delivered",
                status_updated_at=now, provider_message_id="synthetic-retained-id", rendered_message="Retained synthetic text"))
        rows.update({"agencies": agency, "client_groups": group, "passport_submissions": passenger,
            "whatsapp_broadcast_groups": broadcast, "whatsapp_broadcast_recipients": recipient,
            "whatsapp_message_logs": message})
        before = snapshot()
        helper_result = None
        if release_helper:
            from scripts.qualify_document_distribution_release import exercise_release_helper

            helper_result = exercise_release_helper(engine, environment, migrate, message)
            assert snapshot() == before
        with engine.begin() as held:
            held.execute(text("LOCK TABLE passport_submissions IN ACCESS EXCLUSIVE MODE"))
            migrate("upgrade", TARGET, success=False)
            assert held.scalar(text("SELECT version_num FROM alembic_version")) == SOURCE
        assert snapshot() == before
        migrate("upgrade", "0139_passenger_display_name")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT display_name FROM passport_submissions WHERE id=:id"), {"id": passenger}) is None
        migrate("upgrade", TARGET)
        context = {"version": 1, "client_group_id": str(group), "document_type": "visa", "passenger_ids": [str(passenger)]}
        with Session(engine) as session:
            stored_passenger = session.get(PassportSubmissionModel, passenger)
            stored_message = session.get(WhatsAppMessageLogModel, message)
            assert stored_passenger.display_name is None and stored_message.document_update_context is None
            stored_passenger.display_name = "SYNTHETIC OFFICE LABEL"
            stored_message.document_update_context = context
            session.flush()
            session.rollback()
        with engine.connect() as connection:
            assert connection.scalar(select(PassportSubmissionModel.display_name).where(PassportSubmissionModel.id == passenger)) is None
            assert connection.scalar(select(WhatsAppMessageLogModel.document_update_context).where(WhatsAppMessageLogModel.id == message)) is None
        with engine.begin() as connection:
            connection.execute(update(PassportSubmissionModel).where(PassportSubmissionModel.id == passenger)
                .values(display_name="SYNTHETIC OFFICE LABEL", updated_at=before["passport_submissions"]["updated_at"]))
            connection.execute(update(WhatsAppMessageLogModel).where(WhatsAppMessageLogModel.id == message).values(document_update_context=context))
        with Session(engine) as session:
            assert session.get(PassportSubmissionModel, passenger).display_name == "SYNTHETIC OFFICE LABEL"
            assert session.get(WhatsAppMessageLogModel, message).document_update_context == context
        after_write = snapshot()
        differences = {table: {key: [before[table].get(key), value]
            for key, value in values.items() if before[table].get(key) != value}
            for table, values in after_write.items() if values != before[table]}
        # The existing database trigger advances the group's roster revision
        # for a passenger edit. That is an intended edit effect, not migration
        # data loss; all identities, passport fields, and message history stay.
        assert all(table == "client_groups" and set(changes) == {"roster_revision"}
            for table, changes in differences.items()), differences
        before_downgrade = after_write
        migrate("downgrade", SOURCE)
        assert snapshot() == before_downgrade
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == SOURCE
            assert connection.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND ((table_name='passport_submissions' AND column_name='display_name') OR (table_name='whatsapp_message_logs' AND column_name='document_update_context'))")) == 0
        migrate("upgrade", TARGET)
        assert snapshot() == before_downgrade
        return {"source": SOURCE, "target": TARGET, "upgrade_and_retry_passed": True,
            "lock_timeout_atomic_rollback_passed": True, "orm_read_write_rollback_passed": True,
            "downgrade_reupgrade_passed": True, "preexisting_rows_and_fields_retained": True,
            "synthetic_only": True, "messages_sent": 0, "release_helper": helper_result}
    finally:
        engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()


if __name__ == "__main__":
    print(json.dumps(qualify()), flush=True)
