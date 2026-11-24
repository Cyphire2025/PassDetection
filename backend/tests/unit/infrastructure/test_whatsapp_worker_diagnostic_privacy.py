"""Unexpected transport text must not become durable passenger-facing diagnostics."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.infrastructure.whatsapp import worker_runtime
from tests.unit.infrastructure.test_whatsapp_retry_transactions import _seed_batch


async def test_unexpected_provider_error_is_safe_and_never_automatically_resent(
    db_session,
    monkeypatch,
):
    batch_id, _ = await _seed_batch(db_session, ["queued"])
    secret = "synthetic-passport-P1234567-token-PRIVATE\nexternal-detail"

    @asynccontextmanager
    async def session_factory():
        yield db_session

    send = AsyncMock(side_effect=RuntimeError(secret))
    monkeypatch.setattr(worker_runtime, "AsyncSessionFactory", session_factory)
    monkeypatch.setattr(worker_runtime, "send_whatsapp_template", send)
    options = dict(
        batch_id=str(batch_id),
        message_type="welcome",
        message_content="Synthetic update",
        passport_link=None,
    )

    await worker_runtime.run_whatsapp_broadcast(**options)
    await worker_runtime.run_whatsapp_broadcast(**options)

    saved = (await db_session.execute(select(WhatsAppMessageLogModel))).scalar_one()
    assert saved.status == "delivery_unknown"
    send.assert_awaited_once()
    assert secret not in saved.error_message
    assert "automatic resend" in saved.error_message
