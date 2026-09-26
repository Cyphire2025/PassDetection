from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import delete, select

from app.application.interfaces.audit_integrity_sink import AuditIntegrityCheckpoint
from app.infrastructure.audit.checkpoint_codec import AuditIntegrityError, encode, object_key
from app.infrastructure.audit.checkpoint_service import verify_and_publish
from app.infrastructure.audit.s3_checkpoint_sink import S3AuditIntegritySink
from app.infrastructure.database.models import AuditChainHeadModel, AuditLogModel
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository,
    audit_entry_hash,
)


class Store:
    def __init__(self):
        self.events = {}
        self.meta = SimpleNamespace(events=SimpleNamespace(register=lambda event, handler: self.events.__setitem__(event, handler)))
        self.objects = {}
        self.lock, self.versioning = "Enabled", "Enabled"
        self.markers = []
        self.page_size = 1000

    def get_bucket_versioning(self, **kwargs):
        return {"Status": self.versioning}

    def get_object_lock_configuration(self, **kwargs):
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": self.lock}}

    def put_object(self, **kwargs):
        request = SimpleNamespace(headers={})
        self.events["before-sign.s3.PutObject"](request)
        assert request.headers["If-None-Match"] == "*"
        key = kwargs["Key"]
        if key in self.objects:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}, "ResponseMetadata": {"HTTPStatusCode": 412}}, "PutObject")
        self.objects[key] = {**kwargs, "VersionId": "v1"}
        return {"VersionId": "v1"}

    def get_object(self, **kwargs):
        item = self.objects[kwargs["Key"]]
        return {**item, "Body": io.BytesIO(item["Body"])}

    def get_object_retention(self, **kwargs):
        item = self.objects[kwargs["Key"]]
        return {"Retention": {"Mode": item["ObjectLockMode"], "RetainUntilDate": item["ObjectLockRetainUntilDate"]}}

    def get_object_legal_hold(self, **kwargs):
        return {"LegalHold": {"Status": self.objects[kwargs["Key"]]["ObjectLockLegalHoldStatus"]}}

    def list_object_versions(self, **kwargs):
        keys = sorted(key for key in self.objects if key.startswith(kwargs["Prefix"]) and key > kwargs.get("KeyMarker", ""))
        selected = keys[:self.page_size]
        result = {"Versions": [{"Key": key, "VersionId": "v1", "IsLatest": True} for key in selected],
                  "DeleteMarkers": self.markers, "IsTruncated": len(keys) > len(selected)}
        if result["IsTruncated"]:
            result.update(NextKeyMarker=selected[-1], NextVersionIdMarker="v1")
        return result


@pytest.fixture
def sink():
    key = Ed25519PrivateKey.generate()
    return S3AuditIntegritySink(Store(), "synthetic-audit-only", public_keys=[key.public_key()], private_key=key)


def checkpoint(sequence=1, hash_value="a" * 64):
    return AuditIntegrityCheckpoint("global", 1, sequence, hash_value, datetime.now(UTC))


async def test_conditional_idempotent_signed_publication_and_paginated_verification(sink):
    first = checkpoint()
    await sink.publish(first)
    await sink.publish(checkpoint())  # observation timestamp may change, anchored identity may not
    await sink.publish(checkpoint(2))
    sink.client.page_size = 1
    found = [item async for item in sink.checkpoints()]
    assert [item.last_sequence for item in found] == [1, 2]
    assert found[0] == first
    assert len(sink.client.objects) == 2
    with pytest.raises(AuditIntegrityError, match="conflicts"):
        await sink.publish(checkpoint(hash_value="b" * 64))


@pytest.mark.parametrize("fault", ["signature", "retention", "legal_hold", "overwrite", "delete_marker", "key_binding", "oversized"])
async def test_tampered_or_unprotected_external_checkpoint_fails_closed(sink, fault):
    original = checkpoint()
    await sink.publish(original)
    item = sink.client.objects[object_key(original)]
    if fault == "signature":
        body = json.loads(item["Body"])
        body["checkpoint"]["last_hash"] = "b" * 64
        item["Body"] = json.dumps(body).encode()
    elif fault == "retention":
        item["ObjectLockRetainUntilDate"] = original.observed_at + timedelta(days=1)
    elif fault == "legal_hold":
        item["ObjectLockLegalHoldStatus"] = "OFF"
    elif fault == "overwrite":
        listing = sink.client.list_object_versions
        sink.client.list_object_versions = lambda **kw: {**listing(**kw), "Versions": [{"Key": object_key(original), "VersionId": "old", "IsLatest": False}]}
    elif fault == "delete_marker":
        sink.client.markers = [{"Key": object_key(original), "VersionId": "deleted"}]
    elif fault == "key_binding":
        item["Body"] = encode(checkpoint(2), sink.private_key)
    else:
        item["Body"] = b"x" * 4097
    with pytest.raises(AuditIntegrityError):
        _ = [item async for item in sink.checkpoints()]


@pytest.mark.parametrize("fault", ["lock", "versioning"])
async def test_publication_requires_immutable_destination_before_put(sink, fault):
    setattr(sink.client, fault, "Disabled")
    with pytest.raises(AuditIntegrityError):
        await sink.publish(checkpoint())
    assert sink.client.objects == {}


async def test_empty_external_store_cannot_claim_nonempty_database_is_anchored(db_session, sink):
    await AuditLogRepository(db_session).record(action="synthetic.read", entity_type="synthetic")
    with pytest.raises(AuditIntegrityError, match="no_independent_anchor"):
        await verify_and_publish(db_session, sink, publish=False)
    assert sink.client.objects == {}


async def test_verify_only_identity_does_not_need_or_publish_with_private_key(sink):
    original = checkpoint()
    await sink.publish(original)
    verifier = S3AuditIntegritySink(sink.client, sink.bucket, public_keys=list(sink.keys.values()))
    assert [item async for item in verifier.checkpoints()] == [original]
    with pytest.raises(AuditIntegrityError, match="signing_key_required"):
        await verifier.publish(checkpoint(2))
    wrong = S3AuditIntegritySink(sink.client, sink.bucket, public_keys=[Ed25519PrivateKey.generate().public_key()])
    with pytest.raises(AuditIntegrityError, match="signature"):
        _ = [item async for item in wrong.checkpoints()]


@pytest.mark.parametrize("fault", ["content", "truncation", "whole_scope", "consistent_rewrite", "head_only"])
async def test_independent_anchor_catches_database_operator_tampering(db_session, sink, fault):
    repo = AuditLogRepository(db_session)
    row = await repo.record(action="synthetic.read", entity_type="synthetic", metadata={"count": 1})
    initial = await verify_and_publish(db_session, sink, publish=True)
    assert initial["published_checkpoints"] == 1
    assert (await verify_and_publish(db_session, sink, publish=False))["verified_anchors"] == 1
    head = await db_session.scalar(select(AuditChainHeadModel))
    if fault in {"truncation", "whole_scope"}:
        await db_session.execute(delete(AuditLogModel))
        if fault == "whole_scope":
            await db_session.execute(delete(AuditChainHeadModel))
        else:
            head.last_sequence, head.last_hash = 0, "0" * 64
    elif fault == "head_only":
        head.last_hash = "f" * 64
    else:
        row.action = "rewritten.event"
        if fault == "consistent_rewrite":
            row.entry_hash = audit_entry_hash(scope_key="global", sequence=1, previous_hash=row.previous_hash,
                record_id=row.id, agency_id=None, user_id=None, actor_email=None, action=row.action,
                entity_type=row.entity_type, entity_id=None, ip_address=None, result="success", metadata=row.metadata_json, created_at=row.created_at)
            head.last_hash = row.entry_hash
    await db_session.flush()
    with pytest.raises(AuditIntegrityError):
        await verify_and_publish(db_session, sink, publish=True)
    assert len(sink.client.objects) == 1  # never anchor the corrupted replacement
