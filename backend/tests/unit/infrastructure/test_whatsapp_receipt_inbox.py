"""Real ORM/HTTP receipt races, replay isolation and failure recovery."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from starlette.requests import Request

from app.infrastructure.database.gc_mobile_models import MobileOTPChallengeModel
from app.infrastructure.database.models import (
    AuditLogModel,
    DocumentWhatsAppDeliveryModel,
    PassengerQRTokenModel,
    PassengerQrWhatsAppDeliveryModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppProviderMessageBindingModel,
    WhatsAppProviderReceiptModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp import receipt_runtime
from app.infrastructure.whatsapp.phone_welcome import require_welcome_delivered
from app.infrastructure.whatsapp.receipt_bindings import (
    ProviderBindingConflict,
    bind_provider_message,
    bind_source_provider_message,
    commit_private_provider_outcome,
    source_identity,
)
from app.infrastructure.whatsapp.receipt_inbox import (
    VerifiedReceipt,
    parse_verified_receipts,
    persist_verified_receipts,
)
from app.infrastructure.whatsapp.receipt_retention import apply_receipt_retention
from app.infrastructure.whatsapp.receipt_runtime import reconcile_pending_receipts
from app.presentation.api.v1.routes import whatsapp_webhook
from tests.unit.infrastructure.test_phone_welcome import PHONE, _attempt

ACCOUNT = "test-provider-account"
SECRET = "receipt-test-secret"
NOW = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


async def seed_source(session, kind):
    welcome, passenger = await _attempt(session)
    shared = dict(
        id=uuid.uuid4(),
        agency_id=welcome.agency_id,
        group_id=welcome.group_id,
        passenger_id=passenger.id,
        send_batch_id=uuid.uuid4(),
        passenger_name="Test traveller",
        phone_number=PHONE,
        normalized_phone_number=PHONE,
        template_name="approved_test",
        status="processing",
        attempt_count=1,
    )
    if kind == "traveller_welcome":
        welcome.status = "processing"
        source = welcome
    elif kind == "document":
        source = DocumentWhatsAppDeliveryModel(
            **shared, document_type="visa", document_filename="test.pdf"
        )
    elif kind == "qr":
        token_id = uuid.uuid4()
        session.add(
            PassengerQRTokenModel(
                id=token_id,
                agency_id=welcome.agency_id,
                passenger_id=passenger.id,
                token_hash=token_id.hex,
                expires_at=NOW + timedelta(days=30),
            )
        )
        await session.flush()
        source = PassengerQrWhatsAppDeliveryModel(
            **shared, qr_token_id=token_id, template_parameter_values=["hello"]
        )
    elif kind == "broadcast":
        recipient_id, log_id, batch_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        session.add(
            WhatsAppBroadcastRecipientModel(
                id=recipient_id,
                agency_id=welcome.agency_id,
                broadcast_group_id=welcome.broadcast_group_id,
                phone_number=PHONE,
                normalized_phone_number=PHONE,
            )
        )
        await session.flush()
        source = WhatsAppMessageLogModel(
            id=log_id,
            batch_id=batch_id,
            agency_id=welcome.agency_id,
            recipient_id=recipient_id,
            broadcast_group_id=welcome.broadcast_group_id,
            message_type="reminder",
            normalized_phone_number=PHONE,
            status="processing",
        )
        session.add(
            WhatsAppRecipientMessageStateModel(
                id=uuid.uuid4(),
                batch_id=batch_id,
                agency_id=welcome.agency_id,
                recipient_id=recipient_id,
                broadcast_group_id=welcome.broadcast_group_id,
                message_type="reminder",
                status="processing",
            )
        )
    else:
        source = MobileOTPChallengeModel(
            id=uuid.uuid4(),
            agency_id=welcome.agency_id,
            subject_type="passenger",
            purpose="login",
            phone_lookup_hash="a" * 64,
            challenge_token_hash=uuid.uuid4().hex * 2,
            code_hash="hashed-code",
            provider="whatsapp",
            status="pending",
            attempt_count=0,
            max_attempts=5,
            resend_count=0,
            max_resends=3,
            resend_available_at=NOW + timedelta(seconds=30),
            created_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
    session.add(source)
    await session.commit()
    return source


def event(provider_id="wamid.test", status="delivered", timestamp=NOW, account=ACCOUNT):
    return VerifiedReceipt(
        account, provider_id, status, timestamp, "131026" if status == "failed" else None
    )


async def signed_webhook(session, monkeypatch, events, *, valid=True):
    monkeypatch.setattr(
        whatsapp_webhook,
        "get_settings",
        lambda: SimpleNamespace(whatsapp_app_secret=SECRET, app_env="production"),
    )
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": item.provider_phone_number_id},
                            "statuses": [
                                {
                                    "id": item.provider_message_id,
                                    "status": item.provider_status,
                                    "timestamp": str(int(item.provider_status_at.timestamp()))
                                    if item.provider_status_at
                                    else None,
                                    "errors": [
                                        {
                                            "code": item.provider_error_code,
                                            "message": "RAW PHONE AND OTP MUST NOT BE STORED",
                                        }
                                    ]
                                    if item.provider_error_code
                                    else [],
                                }
                            ],
                        }
                    }
                ]
            }
            for item in events
        ]
    }
    raw = json.dumps(payload).encode()
    request = Request(
        {"type": "http", "method": "POST", "path": "/webhook", "headers": []},
        receive=AsyncMock(return_value={"type": "http.request", "body": raw, "more_body": False}),
    )
    signature = (
        "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if valid
        else "sha256=invalid"
    )
    return await whatsapp_webhook.receive_whatsapp_webhook(request, signature, session)


@pytest.mark.parametrize("kind", ["broadcast", "traveller_welcome", "document", "qr", "otp"])
async def test_early_signed_receipt_replays_after_sender_commit_without_second_webhook(
    db_session, monkeypatch, kind
):
    source = await seed_source(db_session, kind)
    source_id, agency_id = source.id, source.agency_id
    status = "failed" if kind == "otp" else "delivered"
    receipt = event(status=status, timestamp=datetime.now(UTC))
    ack = await signed_webhook(db_session, monkeypatch, [receipt])
    assert ack.processed_statuses == 0
    assert (
        await db_session.scalar(select(func.count()).select_from(WhatsAppProviderReceiptModel)) == 1
    )
    if kind == "otp":
        source.provider_reference = receipt.provider_message_id
    else:
        source.provider_message_id = receipt.provider_message_id
        source.status = "submitted"
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    await db_session.commit()
    assert (
        await reconcile_pending_receipts(db_session, now=datetime.now(UTC) + timedelta(minutes=2))
    ) == {"applied": 1}
    await db_session.refresh(source)
    assert source.id == source_id
    assert source.status == ("cancelled" if kind == "otp" else "delivered")
    if kind == "traveller_welcome":
        assert await require_welcome_delivered(db_session, agency_id=agency_id, phone=PHONE)
    assert await signed_webhook(db_session, monkeypatch, [receipt, receipt])
    assert (
        await db_session.scalar(select(func.count()).select_from(WhatsAppProviderReceiptModel)) == 1
    )
    if kind == "otp":
        audits = list(
            (
                await db_session.scalars(
                    select(AuditLogModel).where(
                        AuditLogModel.action == "mobile.otp_delivery_status"
                    )
                )
            ).all()
        )
        assert len(audits) == 1
        assert "RAW" not in json.dumps(audits[0].metadata_json)


async def test_invalid_signature_is_not_persisted(db_session, monkeypatch):
    with pytest.raises(HTTPException) as error:
        await signed_webhook(db_session, monkeypatch, [event()], valid=False)
    assert error.value.status_code == 403
    assert (
        await db_session.scalar(select(func.count()).select_from(WhatsAppProviderReceiptModel)) == 0
    )


async def test_webhook_database_failure_is_not_acknowledged(db_session, monkeypatch):
    monkeypatch.setattr(
        whatsapp_webhook,
        "persist_verified_receipts",
        AsyncMock(side_effect=RuntimeError("database unavailable")),
    )
    with pytest.raises(HTTPException) as error:
        await signed_webhook(db_session, monkeypatch, [event()])
    assert error.value.status_code == 503


async def test_reducer_failure_keeps_committed_receipt_and_does_not_block_next(
    db_session, monkeypatch
):
    first = await seed_source(db_session, "document")
    first.provider_message_id, first.status = "wamid.one", "delivery_unknown"
    await bind_source_provider_message(db_session, first, provider_phone_number_id=ACCOUNT)
    await db_session.commit()
    ids = await persist_verified_receipts(
        db_session, [event("wamid.one"), event("wamid.unmatched")], now=NOW
    )
    await db_session.commit()
    original = receipt_runtime._apply_to_source
    monkeypatch.setattr(
        receipt_runtime, "_apply_to_source", AsyncMock(side_effect=RuntimeError("test crash"))
    )
    assert await reconcile_pending_receipts(db_session, receipt_ids=ids, now=NOW) == {
        "retry": 1,
        "pending": 1,
    }
    await db_session.refresh(first)
    assert first.status == "delivery_unknown"
    monkeypatch.setattr(receipt_runtime, "_apply_to_source", original)
    outcomes = await reconcile_pending_receipts(db_session, now=NOW + timedelta(minutes=2))
    assert outcomes == {"pending": 1, "applied": 1} or outcomes == {"applied": 1, "pending": 1}
    await db_session.refresh(first)
    assert first.status == "delivered"


@pytest.mark.parametrize("kind", ["document", "qr"])
async def test_old_receipt_cannot_update_reused_delivery_row(db_session, kind):
    source = await seed_source(db_session, kind)
    source.provider_message_id = "wamid.old"
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    await db_session.commit()
    source.send_batch_id, source.provider_message_id, source.status = (
        uuid.uuid4(),
        "wamid.new",
        "submitted",
    )
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    ids = await persist_verified_receipts(db_session, [event("wamid.old", "failed")], now=NOW)
    await db_session.commit()
    assert await reconcile_pending_receipts(db_session, receipt_ids=ids, now=NOW) == {
        "superseded": 1
    }
    await db_session.refresh(source)
    assert source.status == "submitted" and source.provider_message_id == "wamid.new"


@pytest.mark.parametrize("kind", ["document", "qr", "traveller_welcome", "broadcast"])
async def test_out_of_order_and_failure_never_regress_read(db_session, kind):
    source = await seed_source(db_session, kind)
    source.provider_message_id, source.status = "wamid.test", "submitted"
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    await db_session.commit()
    for status, offset in [("read", 2), ("sent", 1), ("failed", 3)]:
        ids = await persist_verified_receipts(
            db_session, [event(status=status, timestamp=NOW + timedelta(seconds=offset))], now=NOW
        )
        await db_session.commit()
        assert await reconcile_pending_receipts(db_session, receipt_ids=ids, now=NOW) == {
            "applied": 1
        }
    await db_session.refresh(source)
    assert source.status == "read"


async def test_binding_cannot_be_reassigned_and_account_mismatch_is_terminal(db_session):
    source = await seed_source(db_session, "document")
    source.provider_message_id = "wamid.test"
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    await db_session.commit()
    kind, source_id, attempt = source_identity(source)
    with pytest.raises(ProviderBindingConflict):
        await bind_provider_message(
            db_session,
            source_kind=kind,
            source_id=source_id,
            source_attempt_key=attempt,
            agency_id=source.agency_id,
            provider_phone_number_id=ACCOUNT,
            provider_message_id="different-id",
        )
    await db_session.rollback()
    ids = await persist_verified_receipts(db_session, [event(account="other-account")], now=NOW)
    await db_session.commit()
    assert await reconcile_pending_receipts(db_session, receipt_ids=ids, now=NOW) == {"conflict": 1}


async def test_legacy_match_is_exact_and_unambiguous(db_session):
    source = await seed_source(db_session, "document")
    source.provider_message_id = "wamid.legacy"
    await db_session.commit()
    ids = await persist_verified_receipts(db_session, [event("wamid.legacy")], now=NOW)
    await db_session.commit()
    assert await reconcile_pending_receipts(db_session, receipt_ids=ids, now=NOW) == {"applied": 1}
    binding = await db_session.scalar(select(WhatsAppProviderMessageBindingModel))
    assert binding.source_id == source.id and binding.provider_phone_number_id == ""


@pytest.mark.parametrize("kind", ["document", "qr"])
async def test_known_provider_id_survives_commit_failure_without_resend(
    db_session, monkeypatch, kind
):
    source = await seed_source(db_session, kind)
    source_id = source.id
    source.provider_message_id, source.provider_media_id, source.status = (
        "wamid.test",
        "media-test",
        "submitted",
    )
    commit = db_session.commit
    calls = 0

    async def interrupted_commit():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("test interrupted commit")
        await commit()

    monkeypatch.setattr(db_session, "commit", interrupted_commit)
    await commit_private_provider_outcome(db_session, source, provider_phone_number_id=ACCOUNT)
    assert calls == 2
    saved = await db_session.get(type(source), source_id)
    assert saved.status == "submitted" and saved.provider_message_id == "wamid.test"
    assert (
        await db_session.scalar(
            select(func.count()).select_from(WhatsAppProviderMessageBindingModel)
        )
        == 1
    )


async def test_retention_expires_unmatched_without_changing_outbound_state(db_session):
    source = await seed_source(db_session, "traveller_welcome")
    source.provider_message_id, source.status = "wamid.pending", "submitted"
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    await persist_verified_receipts(
        db_session, [event("wamid.unmatched")], now=NOW - timedelta(days=31)
    )
    await db_session.commit()
    result = await apply_receipt_retention(db_session, now=NOW)
    await db_session.commit()
    assert result["expired_whatsapp_receipts"] == 1
    assert result["deleted_whatsapp_receipts"] == 0
    await db_session.refresh(source)
    assert source.status == "submitted"
    result = await apply_receipt_retention(db_session, now=NOW + timedelta(days=8))
    await db_session.commit()
    assert result["deleted_whatsapp_receipts"] == 1
    assert (
        await db_session.scalar(
            select(func.count()).select_from(WhatsAppProviderMessageBindingModel)
        )
        == 1
    )


def test_receipt_dedupe_ignores_envelope_and_raw_error_prose():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": ACCOUNT},
                            "statuses": [
                                {
                                    "id": "wamid.test",
                                    "status": "failed",
                                    "timestamp": "1789466400",
                                    "errors": [{"code": 131026, "message": "private material"}],
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    events, _ = parse_verified_receipts(payload)
    payload["entry"][0]["changes"][0]["value"]["statuses"][0]["errors"][0]["message"] = (
        "different private material"
    )
    repeated, _ = parse_verified_receipts(payload)
    assert events[0].dedupe_key == repeated[0].dedupe_key
    assert "private" not in repr(events[0])


async def test_delayed_reminder_failure_cannot_release_newer_claim(db_session):
    source = await seed_source(db_session, "broadcast")
    source.provider_message_id, source.status = "wamid.old", "submitted"
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    state = await db_session.scalar(select(WhatsAppRecipientMessageStateModel))
    new_batch = uuid.uuid4()
    state.batch_id, state.status = new_batch, "processing"
    ids = await persist_verified_receipts(db_session, [event("wamid.old", "failed")], now=NOW)
    await db_session.commit()
    assert await reconcile_pending_receipts(db_session, receipt_ids=ids, now=NOW) == {"applied": 1}
    await db_session.refresh(state)
    assert state.batch_id == new_batch and state.status == "processing"


@pytest.mark.parametrize("status", ["verified", "consumed", "expired"])
async def test_otp_failure_never_undoes_completed_challenge(db_session, status):
    source = await seed_source(db_session, "otp")
    source.provider_reference, source.status = "wamid.test", status
    if status in {"verified", "consumed"}:
        source.verified_at = NOW
    if status == "consumed":
        source.consumed_at = NOW
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    ids = await persist_verified_receipts(db_session, [event(status="failed")], now=NOW)
    await db_session.commit()
    assert await reconcile_pending_receipts(db_session, receipt_ids=ids, now=NOW) == {"applied": 1}
    await db_session.refresh(source)
    assert source.status == status


async def test_deleted_source_receipt_is_terminal(db_session):
    source = await seed_source(db_session, "document")
    source.provider_message_id = "wamid.test"
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    await db_session.commit()
    await db_session.delete(source)
    ids = await persist_verified_receipts(db_session, [event()], now=NOW)
    await db_session.commit()
    assert await reconcile_pending_receipts(db_session, receipt_ids=ids, now=NOW) == {
        "source_missing": 1
    }


async def test_superseded_binding_retention_preserves_current_binding(db_session):
    source = await seed_source(db_session, "document")
    source.provider_message_id = "wamid.old"
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    await db_session.commit()
    old = await db_session.scalar(select(WhatsAppProviderMessageBindingModel))
    old.created_at = NOW - timedelta(days=40)
    source.send_batch_id, source.provider_message_id = uuid.uuid4(), "wamid.new"
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    await db_session.commit()
    result = await apply_receipt_retention(db_session, now=NOW)
    await db_session.commit()
    assert result["deleted_whatsapp_bindings"] == 1
    remaining = await db_session.scalar(select(WhatsAppProviderMessageBindingModel))
    assert remaining.provider_message_id == "wamid.new"


def test_receipt_reconciler_is_scheduled_on_whatsapp_queue():
    from app.infrastructure.processing.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule["reconcile-whatsapp-receipts"]
    assert schedule["task"] == "whatsapp.reconcile_receipts"
    assert schedule["schedule"] == 60.0
    assert schedule["options"]["queue"] == "whatsapp"


@pytest.mark.parametrize("scheduled", [False, True])
async def test_one_batch_reordered_failure_does_not_hide_earlier_delivery(db_session, scheduled):
    source = await seed_source(db_session, "traveller_welcome")
    source.provider_message_id, source.status = "wamid.test", "submitted"
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    ids = await persist_verified_receipts(
        db_session,
        [
            event(status="failed", timestamp=NOW + timedelta(seconds=2)),
            event(status="read", timestamp=NOW),
        ],
        now=NOW,
    )
    await db_session.commit()
    assert await reconcile_pending_receipts(
        db_session, receipt_ids=None if scheduled else ids, now=NOW
    ) == {"applied": 2}
    await db_session.refresh(source)
    assert source.status == "read"


async def test_application_failure_retries_increase_and_cap_at_one_hour(db_session, monkeypatch):
    source = await seed_source(db_session, "document")
    source.provider_message_id = "wamid.test"
    await bind_source_provider_message(db_session, source, provider_phone_number_id=ACCOUNT)
    ids = await persist_verified_receipts(db_session, [event()], now=NOW)
    await db_session.commit()
    monkeypatch.setattr(
        receipt_runtime,
        "_apply_to_source",
        AsyncMock(side_effect=RuntimeError("temporary failure")),
    )
    now = NOW
    delays = []
    for attempt in range(1, 13):
        assert await reconcile_pending_receipts(db_session, receipt_ids=ids, now=now) == {
            "retry": 1
        }
        receipt = await db_session.get(WhatsAppProviderReceiptModel, ids[0], populate_existing=True)
        assert receipt.attempt_count == attempt and receipt.state == "pending"
        next_at = receipt_runtime.aware(receipt.next_attempt_at)
        delays.append((next_at - now).total_seconds())
        now = next_at
        await db_session.commit()
    assert delays[:4] == [10, 20, 40, 80]
    assert delays[-3:] == [3600, 3600, 3600]
    assert max(delays) == 3600
