"""Real persistence checks for QR phase fences, retry safety, and facade seams."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database.models import PassengerQRTokenModel
from app.infrastructure.whatsapp import qr_delivery_runtime as runtime
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError
from app.infrastructure.whatsapp.private_delivery_policy import (
    lock_private_delivery_group_source_snapshot,
)
from tests.unit.infrastructure.test_private_delivery_policy import (
    _qr_delivery,
    _seed_private_delivery_context,
)


@pytest.fixture
async def qr_work(db_session, monkeypatch):
    if db_session.bind.dialect.name == "sqlite":
        # SQLite ignores the model's PostgreSQL-only partial-index predicate.
        # Reproduce that production constraint here so historical token versions
        # remain allowed while two active tokens for one passenger stay forbidden.
        await db_session.execute(text("DROP INDEX uq_passenger_qr_tokens_one_active_per_passenger"))
        await db_session.execute(
            text(
                "CREATE UNIQUE INDEX uq_passenger_qr_tokens_one_active_per_passenger "
                "ON passenger_qr_tokens (passenger_id) WHERE is_active = 1"
            )
        )
    context = await _seed_private_delivery_context(db_session)
    context["token"].expires_at = datetime.now(tz=UTC) + timedelta(days=1)
    delivery = _qr_delivery(context, status="queued")
    db_session.add(delivery)
    await db_session.commit()
    snapshot = await lock_private_delivery_group_source_snapshot(
        db_session,
        agency_id=context["agency"].id,
        group_id=context["group"].id,
    )
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    render = SimpleNamespace(calls=0)

    def render_image(_payload):
        render.calls += 1
        return b"synthetic-qr-image"

    upload = AsyncMock(return_value="media-id")
    send = AsyncMock(return_value="wamid.synthetic")
    monkeypatch.setattr(runtime, "AsyncSessionFactory", factory)
    monkeypatch.setattr(runtime, "render_attendance_qr_png", render_image)
    monkeypatch.setattr(runtime, "upload_whatsapp_image", upload)
    monkeypatch.setattr(runtime, "send_whatsapp_qr_template", send)

    async def run():
        await runtime.run_qr_whatsapp_broadcast(
            send_batch_id=str(delivery.send_batch_id),
            _delivery_id=delivery.id,
            _source_snapshot=snapshot,
            _client=SimpleNamespace(),
        )
        await db_session.refresh(delivery)

    return SimpleNamespace(
        context=context,
        delivery=delivery,
        factory=factory,
        render=render,
        upload=upload,
        send=send,
        run=run,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoked", "rotated"])
async def test_qr_changed_during_upload_is_never_sent(qr_work, change):
    work = qr_work
    token_id = work.context["token"].id

    async def change_after_media_upload(**_kwargs):
        async with work.factory() as session:
            token = await session.get(PassengerQRTokenModel, token_id)
            if change == "revoked":
                token.is_active = False
            else:
                token.is_active = False
                await session.flush()
                session.add(
                    PassengerQRTokenModel(
                        agency_id=token.agency_id,
                        passenger_id=token.passenger_id,
                        token_hash="new-synthetic-token-hash",
                        token_version=2,
                        qr_payload="pdatt:" + "B" * 43,
                        is_active=True,
                        expires_at=datetime.now(tz=UTC) + timedelta(days=1),
                    )
                )
            await session.commit()
        return "already-uploaded-media"

    work.upload.side_effect = change_after_media_upload
    await work.run()

    work.send.assert_not_awaited()
    assert work.delivery.status == "failed"
    assert work.delivery.provider_media_id == "already-uploaded-media"
    assert "changed after queueing" in work.delivery.error_message


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["submitted", "delivered", "processing"])
async def test_retried_claim_never_repeats_media_or_provider_send(qr_work, db_session, status):
    work = qr_work
    work.delivery.status = status
    await db_session.commit()

    await work.run()

    assert work.render.calls == 0
    work.upload.assert_not_awaited()
    work.send.assert_not_awaited()
    assert work.delivery.status == ("delivery_unknown" if status == "processing" else status)


@pytest.mark.asyncio
@pytest.mark.parametrize("ambiguous", [True, False])
async def test_ambiguous_provider_outcome_is_persisted_once_without_unsafe_error(
    qr_work, ambiguous
):
    work = qr_work
    work.send.side_effect = (
        WhatsAppCloudApiError("safe provider outcome", delivery_unknown=True)
        if ambiguous
        else RuntimeError("synthetic-private-passport-and-token")
    )

    await work.run()
    await work.run()

    assert work.delivery.status == "delivery_unknown"
    assert "synthetic-private-passport-and-token" not in work.delivery.error_message
    assert work.send.await_count == 1
    assert work.upload.await_count == 1


@pytest.mark.asyncio
async def test_known_rate_limit_retries_same_frozen_qr_payload(qr_work, monkeypatch):
    from app.infrastructure.whatsapp import qr_delivery_dispatch

    work = qr_work
    work.send.side_effect = [
        WhatsAppCloudApiError("rate limit", transient=True),
        "wamid.accepted",
    ]
    sleep = AsyncMock()
    monkeypatch.setattr(qr_delivery_dispatch.asyncio, "sleep", sleep)

    await work.run()

    assert work.delivery.status == "submitted"
    assert work.delivery.provider_message_id == "wamid.accepted"
    assert work.send.await_count == 2
    assert work.send.await_args_list[0] == work.send.await_args_list[1]
    sleep.assert_awaited_once_with(1)
    assert work.upload.await_count == 1


@pytest.mark.asyncio
async def test_invalid_reconstruction_never_uploads_or_sends(qr_work, monkeypatch):
    work = qr_work

    def invalid_image(_payload):
        raise ValueError("synthetic-invalid-private-qr")

    monkeypatch.setattr(runtime, "render_attendance_qr_png", invalid_image)
    await work.run()

    assert work.delivery.status == "failed"
    assert "regenerate it before sending" in work.delivery.error_message
    assert "synthetic-invalid-private-qr" not in work.delivery.error_message
    work.upload.assert_not_awaited()
    work.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_qr_fails_before_render_or_upload(qr_work, db_session):
    work = qr_work
    work.context["token"].expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
    await db_session.commit()

    await work.run()

    assert work.delivery.status == "failed"
    assert work.render.calls == 0
    work.upload.assert_not_awaited()
    work.send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("recoverable", [True, False])
async def test_media_upload_retry_does_not_repeat_render_or_send(qr_work, monkeypatch, recoverable):
    from app.infrastructure.whatsapp import qr_delivery_media

    work = qr_work
    error = WhatsAppCloudApiError("safe upload failure", transient=recoverable)
    work.upload.side_effect = [error, "media-retried"] if recoverable else error
    monkeypatch.setattr(qr_delivery_media.asyncio, "sleep", AsyncMock())

    await work.run()

    assert work.render.calls == 1
    assert work.upload.await_count == (2 if recoverable else 1)
    assert work.send.await_count == (1 if recoverable else 0)
    assert work.delivery.status == ("submitted" if recoverable else "failed")


@pytest.mark.asyncio
async def test_known_provider_rejection_is_failed_without_automatic_resend(qr_work):
    work = qr_work
    work.send.side_effect = WhatsAppCloudApiError("safe known rejection")

    await work.run()
    await work.run()

    assert work.delivery.status == "failed"
    work.send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "processing", "submitted"])
async def test_terminal_batch_failure_retains_accepted_or_uncertain_status(
    qr_work, db_session, status
):
    work = qr_work
    work.delivery.status = status
    await db_session.commit()

    await runtime.mark_qr_batch_failed(
        send_batch_id=str(work.delivery.send_batch_id),
        error_message="safe worker failure",
    )
    await db_session.refresh(work.delivery)

    assert (
        work.delivery.status
        == {
            "queued": "failed",
            "processing": "delivery_unknown",
            "submitted": "submitted",
        }[status]
    )
    work.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_known_media_and_provider_references_are_persisted_together(qr_work, db_session):
    work = qr_work
    await runtime._mark_delivery(
        work.delivery.id,
        status="submitted",
        error_message=None,
        provider_message_id="wamid.saved",
        provider_media_id="media.saved",
    )
    await db_session.refresh(work.delivery)

    assert work.delivery.status == "submitted"
    assert work.delivery.provider_message_id == "wamid.saved"
    assert work.delivery.provider_media_id == "media.saved"


@pytest.mark.asyncio
async def test_qr_receipts_advance_monotonically_and_ignore_older_failure(qr_work):
    work = qr_work
    now = datetime.now(tz=UTC)
    for status, at in [("sent", now), ("read", now + timedelta(seconds=1))]:
        runtime.apply_qr_provider_status(
            work.delivery,
            provider_status=status,
            provider_status_at=at,
            error_message=None,
            now=at,
        )
    runtime.apply_qr_provider_status(
        work.delivery,
        provider_status="failed",
        provider_status_at=now,
        error_message="older failure",
        now=now + timedelta(seconds=2),
    )

    assert work.delivery.status == "read"
    assert work.delivery.provider_status_at == now + timedelta(seconds=1)
    assert work.delivery.error_message is None
