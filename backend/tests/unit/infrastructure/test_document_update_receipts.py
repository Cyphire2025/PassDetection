"""Text-update receipts stay in their own ledger and preserve PDF outcomes."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.infrastructure.database.models import WhatsAppRecipientMessageStateModel
from app.infrastructure.whatsapp.document_update_runtime import run_document_update_broadcast
from app.infrastructure.whatsapp.receipt_inbox import VerifiedReceipt, persist_verified_receipts
from app.infrastructure.whatsapp.receipt_runtime import reconcile_pending_receipts
from tests.unit.infrastructure.test_document_update_runtime import seed_update


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["delivered", "failed"])
async def test_update_receipt_changes_only_its_log_not_document_or_generic_send_state(
    db_session, monkeypatch, status
):
    log, document_delivery, send = await seed_update(db_session, monkeypatch)
    await run_document_update_broadcast(batch_id=str(log.batch_id))
    await db_session.refresh(log)
    now = datetime.now(UTC)
    receipt_ids = await persist_verified_receipts(
        db_session,
        [VerifiedReceipt("fixture-account", log.provider_message_id, status, now,
                         "131026" if status == "failed" else None)],
        now=now,
    )
    await db_session.commit()
    assert await reconcile_pending_receipts(db_session, receipt_ids=receipt_ids, now=now) == {"applied": 1}
    await db_session.refresh(log)
    await db_session.refresh(document_delivery)
    assert log.status == status
    assert document_delivery.status == "queued"
    assert await db_session.scalar(select(WhatsAppRecipientMessageStateModel).where(
        WhatsAppRecipientMessageStateModel.message_type == "document_update"
    )) is None
    await run_document_update_broadcast(batch_id=str(log.batch_id))
    send.assert_awaited_once()
