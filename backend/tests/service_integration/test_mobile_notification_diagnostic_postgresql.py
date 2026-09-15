"""The operator diagnostic executes real SELECTs and a read-only transaction."""

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from scripts.diagnose_mobile_notifications import collect_evidence
from tests.service_integration.test_whatsapp_receipts_postgresql import pg_factory as pg_factory

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"),
]


async def test_operator_diagnostic_executes_without_writes_or_secrets(pg_factory, monkeypatch):
    monkeypatch.setenv("APP_REVISION", "a" * 40)
    async with pg_factory() as session:
        await session.execute(text("CREATE TABLE alembic_version (version_num varchar(64))"))
        await session.execute(text("INSERT INTO alembic_version VALUES ('0094_whatsapp_receipt_inbox')"))
        await session.commit()
        result = await collect_evidence(session)
        assert result["database_schema"] == ["0094_whatsapp_receipt_inbox"]
        assert result["app_revision"] == "a" * 40
        assert result["announcements"] == []
        assert result["registration_inventory"] == []
        assert "token_ciphertext" not in json.dumps(result, default=str)
        assert (await session.scalar(text("SHOW transaction_read_only"))) == "on"
        with pytest.raises(DBAPIError, match="read-only"):
            await session.execute(text("INSERT INTO alembic_version VALUES ('must-not-write')"))
        await session.rollback()
