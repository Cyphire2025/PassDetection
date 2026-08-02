from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.documents import verification_staging
from app.infrastructure.documents.document_matcher import ClassifiedDocument
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.documents.verification_staging import (
    StagedDocumentReceipt,
    VerificationReceiptBatchTooLargeError,
    VerificationReceiptCipher,
    VerificationReceiptError,
    VerificationReceiptExpiredError,
    VerificationReceiptScopeChangedError,
    VerificationStagingInput,
    decode_verification_receipts,
    stage_verified_documents,
    validate_verification_receipt_token_batch,
    verification_scope_fingerprints,
)


class _Storage:
    def __init__(self, *, fail_filename: str | None = None) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []
        self.fail_filename = fail_filename

    async def upload_file(self, content: bytes, key: str, _content_type: str) -> str:
        if self.fail_filename and self.fail_filename in key:
            raise RuntimeError("storage unavailable")
        self.objects[key] = content
        return key

    async def delete_files(self, keys: list[str]) -> int:
        self.deleted.extend(keys)
        for key in keys:
            self.objects.pop(key, None)
        return len(keys)


@pytest.fixture
def receipt_cipher(monkeypatch: pytest.MonkeyPatch) -> VerificationReceiptCipher:
    monkeypatch.setattr(
        verification_staging,
        "get_settings",
        lambda: SimpleNamespace(
            storage_cleanup_encryption_key=None,
            app_secret_key="test-document-verification-secret",
            storage_cleanup_encryption_key_version=1,
            storage_cleanup_decryption_keys={},
        ),
    )
    return VerificationReceiptCipher()


def _classification(filename: str = "visa.pdf") -> ClassifiedDocument:
    return ClassifiedDocument(
        original_filename=filename,
        detected_type="visa",
        accepted=True,
        reason="Verified visa structure",
        text="E-VISA Passport number A1234567 Full name TEST PASSENGER",
        extracted_name="TEST PASSENGER",
        extracted_passport_number="A1234567",
        extracted_reference="EV123",
    )


def _receipt(*, now: datetime, **overrides: object) -> StagedDocumentReceipt:
    now = now.replace(microsecond=0)
    agency_id = overrides.pop("agency_id", uuid.uuid4())
    actor_id = overrides.pop("actor_id", uuid.uuid4())
    receipt_id = overrides.pop("receipt_id", uuid.uuid4())
    defaults: dict[str, object] = {
        "receipt_id": receipt_id,
        "agency_id": agency_id,
        "actor_id": actor_id,
        "group_id": uuid.uuid4(),
        "upload_id": uuid.uuid4(),
        "chunk_id": uuid.uuid4(),
        "document_type": "visa",
        "expires_at": now + timedelta(minutes=30),
        "storage_key": (f"document-verification-staging/{agency_id}/{actor_id}/{receipt_id}.pdf"),
        "filename": "visa.pdf",
        "content_type": "application/pdf",
        "byte_count": 4,
        "content_sha256": "0" * 64,
        "roster_fingerprint": "1" * 64,
        "source_fingerprint": "2" * 64,
        "identifiers_fingerprint": "3" * 64,
        "classification": _classification(),
    }
    defaults.update(overrides)
    return StagedDocumentReceipt(**defaults)  # type: ignore[arg-type]


def _decode(
    token: str, receipt: StagedDocumentReceipt, *, now: datetime
) -> list[StagedDocumentReceipt]:
    return decode_verification_receipts(
        [token],
        agency_id=receipt.agency_id,
        actor_id=receipt.actor_id,
        group_id=receipt.group_id,
        upload_id=receipt.upload_id,
        chunk_id=receipt.chunk_id,
        document_type=receipt.document_type,
        roster_fingerprint=receipt.roster_fingerprint,
        source_fingerprint=receipt.source_fingerprint,
        identifiers_fingerprint=receipt.identifiers_fingerprint,
        now=now,
    )


def test_receipt_is_opaque_round_trips_and_rejects_tampering(
    receipt_cipher: VerificationReceiptCipher,
) -> None:
    now = datetime.now(tz=UTC)
    receipt = _receipt(now=now)
    token = receipt_cipher.encrypt(receipt)

    assert receipt.storage_key not in token
    assert receipt.filename not in token
    assert receipt_cipher.decrypt(token) == receipt
    with pytest.raises(VerificationReceiptError):
        receipt_cipher.decrypt(f"{token[:-1]}x")


def test_receipt_round_trip_preserves_unicode_payload(
    receipt_cipher: VerificationReceiptCipher,
) -> None:
    now = datetime.now(tz=UTC)
    filename = "签证-é.pdf"
    receipt = _receipt(
        now=now,
        filename=filename,
        classification=_classification(filename),
    )

    assert receipt_cipher.decrypt(receipt_cipher.encrypt(receipt)) == receipt


def test_receipt_rejects_cross_user_scope_and_arbitrary_storage_key(
    receipt_cipher: VerificationReceiptCipher,
) -> None:
    now = datetime.now(tz=UTC)
    receipt = _receipt(now=now)
    token = receipt_cipher.encrypt(receipt)
    with pytest.raises(VerificationReceiptError):
        decode_verification_receipts(
            [token],
            agency_id=receipt.agency_id,
            actor_id=uuid.uuid4(),
            group_id=receipt.group_id,
            upload_id=receipt.upload_id,
            chunk_id=receipt.chunk_id,
            document_type="visa",
            roster_fingerprint=receipt.roster_fingerprint,
            source_fingerprint=receipt.source_fingerprint,
            identifiers_fingerprint=receipt.identifiers_fingerprint,
            cipher=receipt_cipher,
            now=now,
        )

    malicious = _receipt(now=now, storage_key="document-distribution/foreign.pdf")
    with pytest.raises(VerificationReceiptError):
        _decode(receipt_cipher.encrypt(malicious), malicious, now=now)


@pytest.mark.parametrize("scope_field", ["upload_id", "chunk_id"])
def test_receipt_rejects_cross_upload_or_chunk_replay(
    receipt_cipher: VerificationReceiptCipher,
    scope_field: str,
) -> None:
    now = datetime.now(tz=UTC)
    receipt = _receipt(now=now)
    decode_kwargs = {
        "agency_id": receipt.agency_id,
        "actor_id": receipt.actor_id,
        "group_id": receipt.group_id,
        "upload_id": receipt.upload_id,
        "chunk_id": receipt.chunk_id,
        "document_type": receipt.document_type,
        "roster_fingerprint": receipt.roster_fingerprint,
        "source_fingerprint": receipt.source_fingerprint,
        "identifiers_fingerprint": receipt.identifiers_fingerprint,
        "cipher": receipt_cipher,
        "now": now,
    }
    decode_kwargs[scope_field] = uuid.uuid4()

    with pytest.raises(VerificationReceiptError, match="outside this upload scope"):
        decode_verification_receipts(
            [receipt_cipher.encrypt(receipt)],
            **decode_kwargs,  # type: ignore[arg-type]
        )


def test_receipt_expiry_and_roster_change_return_owned_cleanup_keys(
    receipt_cipher: VerificationReceiptCipher,
) -> None:
    now = datetime.now(tz=UTC)
    receipt = _receipt(now=now)
    token = receipt_cipher.encrypt(receipt)
    with pytest.raises(VerificationReceiptExpiredError) as expired:
        _decode(token, receipt, now=receipt.expires_at)
    assert expired.value.storage_keys == (receipt.storage_key,)

    with pytest.raises(VerificationReceiptScopeChangedError) as changed:
        decode_verification_receipts(
            [token],
            agency_id=receipt.agency_id,
            actor_id=receipt.actor_id,
            group_id=receipt.group_id,
            upload_id=receipt.upload_id,
            chunk_id=receipt.chunk_id,
            document_type="visa",
            roster_fingerprint="f" * 64,
            source_fingerprint=receipt.source_fingerprint,
            identifiers_fingerprint=receipt.identifiers_fingerprint,
            cipher=receipt_cipher,
            now=now,
        )
    assert changed.value.storage_keys == (receipt.storage_key,)


def test_duplicate_receipt_in_one_chunk_is_rejected_but_single_replay_decodes(
    receipt_cipher: VerificationReceiptCipher,
) -> None:
    now = datetime.now(tz=UTC)
    receipt = _receipt(now=now)
    token = receipt_cipher.encrypt(receipt)
    decode_kwargs = {
        "agency_id": receipt.agency_id,
        "actor_id": receipt.actor_id,
        "group_id": receipt.group_id,
        "upload_id": receipt.upload_id,
        "chunk_id": receipt.chunk_id,
        "document_type": receipt.document_type,
        "roster_fingerprint": receipt.roster_fingerprint,
        "source_fingerprint": receipt.source_fingerprint,
        "identifiers_fingerprint": receipt.identifiers_fingerprint,
        "cipher": receipt_cipher,
        "now": now,
    }

    with pytest.raises(VerificationReceiptError):
        decode_verification_receipts([token, token], **decode_kwargs)

    # A sequential retry may safely submit the same opaque receipt; chunk
    # idempotency binds it to the original file hash at the upload route.
    assert decode_verification_receipts([token], **decode_kwargs) == [receipt]
    assert decode_verification_receipts([token], **decode_kwargs) == [receipt]


def test_encoded_receipt_batch_limit_is_enforced_before_decrypt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(verification_staging, "MAX_VERIFICATION_RECEIPT_BATCH_BYTES", 5)

    with pytest.raises(VerificationReceiptBatchTooLargeError):
        validate_verification_receipt_token_batch(["abc", "def"])


def test_decoded_receipt_batch_limit_is_incremental(
    monkeypatch: pytest.MonkeyPatch,
    receipt_cipher: VerificationReceiptCipher,
) -> None:
    now = datetime.now(tz=UTC)
    receipt_one = _receipt(now=now)
    receipt_two = _receipt(
        now=now,
        agency_id=receipt_one.agency_id,
        actor_id=receipt_one.actor_id,
        group_id=receipt_one.group_id,
        upload_id=receipt_one.upload_id,
        chunk_id=receipt_one.chunk_id,
    )
    one_payload_size = len(verification_staging._serialized_receipt_payload(receipt_one))
    monkeypatch.setattr(
        verification_staging,
        "MAX_VERIFICATION_RECEIPT_DECODED_BATCH_BYTES",
        one_payload_size,
    )
    decode_kwargs = {
        "agency_id": receipt_one.agency_id,
        "actor_id": receipt_one.actor_id,
        "group_id": receipt_one.group_id,
        "upload_id": receipt_one.upload_id,
        "chunk_id": receipt_one.chunk_id,
        "document_type": receipt_one.document_type,
        "roster_fingerprint": receipt_one.roster_fingerprint,
        "source_fingerprint": receipt_one.source_fingerprint,
        "identifiers_fingerprint": receipt_one.identifiers_fingerprint,
        "cipher": receipt_cipher,
        "now": now,
    }

    assert decode_verification_receipts([receipt_cipher.encrypt(receipt_one)], **decode_kwargs) == [
        receipt_one
    ]
    with pytest.raises(VerificationReceiptBatchTooLargeError):
        decode_verification_receipts(
            [receipt_cipher.encrypt(receipt_one), receipt_cipher.encrypt(receipt_two)],
            **decode_kwargs,
        )


@pytest.mark.asyncio
async def test_staging_persists_expiring_cleanup_tombstone(
    monkeypatch: pytest.MonkeyPatch,
    receipt_cipher: VerificationReceiptCipher,
) -> None:
    storage = _Storage()
    tombstones: list[dict[str, object]] = []

    async def persist(**kwargs: object) -> uuid.UUID:
        tombstones.append(kwargs)
        return uuid.uuid4()

    monkeypatch.setattr(verification_staging, "persist_storage_cleanup_job", persist)
    agency_id, actor_id, group_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(tz=UTC)
    fingerprints = verification_scope_fingerprints(
        roster_snapshot=(("passenger",),),
        source_snapshot=(("source",),),
        identifiers=(("identifier",),),
    )
    tokens = await stage_verified_documents(
        [
            VerificationStagingInput(
                filename="visa.pdf",
                content=b"%PDF",
                content_type="application/pdf",
                classification=_classification(),
            )
        ],
        agency_id=agency_id,
        actor_id=actor_id,
        group_id=group_id,
        upload_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        document_type="visa",
        roster_fingerprint=fingerprints[0],
        source_fingerprint=fingerprints[1],
        identifiers_fingerprint=fingerprints[2],
        storage=storage,  # type: ignore[arg-type]
        cipher=receipt_cipher,
        now=now,
    )

    assert tokens and len(tokens) == 1
    decoded = receipt_cipher.decrypt(tokens[0])
    assert storage.objects == {decoded.storage_key: b"%PDF"}
    assert tombstones[0]["source"] == "document_verification_staging"
    assert tombstones[0]["storage_keys"] == [decoded.storage_key]
    assert tombstones[0]["not_before"] == decoded.expires_at


@pytest.mark.asyncio
async def test_staging_commits_cleanup_tombstone_before_first_object_write(
    monkeypatch: pytest.MonkeyPatch,
    receipt_cipher: VerificationReceiptCipher,
) -> None:
    events: list[str] = []

    class OrderedStorage(_Storage):
        async def upload_file(self, content: bytes, key: str, content_type: str) -> str:
            events.append("upload")
            return await super().upload_file(content, key, content_type)

    async def persist(**_kwargs: object) -> uuid.UUID:
        events.append("tombstone")
        return uuid.uuid4()

    monkeypatch.setattr(verification_staging, "persist_storage_cleanup_job", persist)
    fingerprints = verification_scope_fingerprints(
        roster_snapshot=(), source_snapshot=(), identifiers=()
    )

    await stage_verified_documents(
        [
            VerificationStagingInput(
                filename="visa.pdf",
                content=b"%PDF",
                content_type="application/pdf",
                classification=_classification(),
            )
        ],
        agency_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        upload_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        document_type="visa",
        roster_fingerprint=fingerprints[0],
        source_fingerprint=fingerprints[1],
        identifiers_fingerprint=fingerprints[2],
        storage=OrderedStorage(),  # type: ignore[arg-type]
        cipher=receipt_cipher,
    )

    assert events == ["tombstone", "upload"]


@pytest.mark.asyncio
async def test_staging_drains_sibling_failure_before_deleting_every_claimed_key(
    monkeypatch: pytest.MonkeyPatch,
    receipt_cipher: VerificationReceiptCipher,
) -> None:
    class PartialFailureStorage(_Storage):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0
            self.late_write_completed = False

        async def upload_file(self, content: bytes, key: str, _content_type: str) -> str:
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("second write failed")
            await asyncio.sleep(0.02)
            self.objects[key] = content
            self.late_write_completed = True
            return key

    storage = PartialFailureStorage()
    persist = AsyncMock()
    monkeypatch.setattr(verification_staging, "persist_storage_cleanup_job", persist)
    fingerprints = verification_scope_fingerprints(
        roster_snapshot=(), source_snapshot=(), identifiers=()
    )

    with pytest.raises(RuntimeError, match="second write failed"):
        await stage_verified_documents(
            [
                VerificationStagingInput(
                    filename=filename,
                    content=payload,
                    content_type="application/pdf",
                    classification=_classification(filename),
                )
                for filename, payload in (("one.pdf", b"one"), ("two.pdf", b"two"))
            ],
            agency_id=uuid.uuid4(),
            actor_id=uuid.uuid4(),
            group_id=uuid.uuid4(),
            upload_id=uuid.uuid4(),
            chunk_id=uuid.uuid4(),
            document_type="visa",
            roster_fingerprint=fingerprints[0],
            source_fingerprint=fingerprints[1],
            identifiers_fingerprint=fingerprints[2],
            storage=storage,  # type: ignore[arg-type]
            cipher=receipt_cipher,
        )

    assert storage.late_write_completed is True
    assert len(storage.deleted) == 2
    assert storage.objects == {}
    persist.assert_awaited_once()


@pytest.mark.asyncio
async def test_oversized_receipt_batch_falls_back_before_any_storage_write(
    monkeypatch: pytest.MonkeyPatch,
    receipt_cipher: VerificationReceiptCipher,
) -> None:
    storage = _Storage()
    persist = AsyncMock()
    monkeypatch.setattr(verification_staging, "persist_storage_cleanup_job", persist)
    monkeypatch.setattr(verification_staging, "MAX_VERIFICATION_RECEIPT_BATCH_BYTES", 1)
    fingerprints = verification_scope_fingerprints(
        roster_snapshot=(), source_snapshot=(), identifiers=()
    )

    tokens = await stage_verified_documents(
        [
            VerificationStagingInput(
                filename="visa.pdf",
                content=b"%PDF",
                content_type="application/pdf",
                classification=_classification(),
            )
        ],
        agency_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        upload_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        document_type="visa",
        roster_fingerprint=fingerprints[0],
        source_fingerprint=fingerprints[1],
        identifiers_fingerprint=fingerprints[2],
        storage=storage,  # type: ignore[arg-type]
        cipher=receipt_cipher,
    )

    assert tokens is None
    assert storage.objects == {}
    persist.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "limit_name",
    [
        "MAX_VERIFICATION_RECEIPT_PAYLOAD",
        "MAX_VERIFICATION_RECEIPT_DECODED_BATCH_BYTES",
    ],
)
async def test_oversized_decoded_receipt_batch_falls_back_before_storage_write(
    monkeypatch: pytest.MonkeyPatch,
    receipt_cipher: VerificationReceiptCipher,
    limit_name: str,
) -> None:
    storage = _Storage()
    persist = AsyncMock()
    monkeypatch.setattr(verification_staging, "persist_storage_cleanup_job", persist)
    monkeypatch.setattr(
        verification_staging,
        limit_name,
        1,
    )
    fingerprints = verification_scope_fingerprints(
        roster_snapshot=(), source_snapshot=(), identifiers=()
    )

    tokens = await stage_verified_documents(
        [
            VerificationStagingInput(
                filename="visa.pdf",
                content=b"%PDF",
                content_type="application/pdf",
                classification=_classification(),
            )
        ],
        agency_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        upload_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        document_type="visa",
        roster_fingerprint=fingerprints[0],
        source_fingerprint=fingerprints[1],
        identifiers_fingerprint=fingerprints[2],
        storage=storage,  # type: ignore[arg-type]
        cipher=receipt_cipher,
    )

    assert tokens is None
    assert storage.objects == {}
    persist.assert_not_awaited()


@pytest.mark.asyncio
async def test_bounded_storage_operations_drain_late_write_before_raising() -> None:
    completed: list[str] = []

    async def delayed_write() -> str:
        await asyncio.sleep(0.02)
        completed.append("late")
        return "late"

    async def failed_write() -> str:
        raise RuntimeError("failed")

    with pytest.raises(RuntimeError, match="failed"):
        await run_bounded_storage_operations([delayed_write, failed_write], concurrency=2)
    assert completed == ["late"]


@pytest.mark.asyncio
async def test_bounded_storage_operations_preserve_cancellation_after_drain() -> None:
    release = asyncio.Event()
    completed: list[str] = []

    async def delayed_write() -> str:
        await release.wait()
        completed.append("finished")
        return "finished"

    task = asyncio.create_task(run_bounded_storage_operations([delayed_write], concurrency=1))
    await asyncio.sleep(0)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completed == ["finished"]
