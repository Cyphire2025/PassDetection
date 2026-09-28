"""Bounded encrypted JSON for computed roster identities, never ORM objects."""

from __future__ import annotations

import json
import uuid
import zlib
from dataclasses import asdict
from datetime import datetime

from cryptography.fernet import Fernet

from app.application.use_cases.passports.submission_view import (
    DuplicateClusterPage,
    ExpiryAlert,
    PreparedSubmissionView,
    SubmissionViewEntry,
    SubmissionViewIdentity,
)

MAX_RAW_BYTES = 8 * 1024 * 1024
MAX_STORED_BYTES = 4 * 1024 * 1024


def encode(index: PreparedSubmissionView, cipher: Fernet, identity: str) -> bytes | None:
    members = {}
    pages = []
    for page in index.pages:
        entries = []
        for entry in page:
            submission = entry.submission
            if entry.duplicate_cluster_id is not None and entry.duplicate_cluster_id not in members:
                members[entry.duplicate_cluster_id] = [str(value) for value in entry.duplicate_cluster_member_ids]
            entries.append([str(submission.id), submission.extraction_revision, submission.updated_at.isoformat(),
                            entry.duplicate_cluster_id, entry.duplicate_cluster_size, entry.verification_confidence])
        pages.append(entries)
    payload = {"v": 2, "identity": identity, "pages": pages, "members": members,
               "clusters": [[asdict(cluster) for cluster in page] for page in index.clusters],
               "ordered": [str(value) for value in index.ordered_submission_ids],
               "group_total": index.group_total, "total": index.total, "page_size": index.page_size,
               "document_follow_up_count": index.document_follow_up_count,
               "boundaries": index.cluster_boundaries_preserved, "alerts": [asdict(alert) for alert in index.expiry_alerts]}
    raw = json.dumps(payload, separators=(",", ":"), default=str).encode()
    if len(raw) > MAX_RAW_BYTES:
        return None
    encrypted = cipher.encrypt(zlib.compress(raw))
    return encrypted if len(encrypted) <= MAX_STORED_BYTES else None


def decode(stored: bytes, cipher: Fernet, identity: str) -> PreparedSubmissionView:
    if len(stored) > MAX_STORED_BYTES:
        raise ValueError("oversized roster cache")
    compressed = cipher.decrypt(stored, ttl=65)
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, MAX_RAW_BYTES + 1)
    if len(raw) > MAX_RAW_BYTES or not decoder.eof or decoder.unused_data:
        raise ValueError("invalid bounded roster payload")
    value = json.loads(raw)
    if value["v"] != 2 or value["identity"] != identity:
        raise ValueError("roster cache identity mismatch")
    members = {key: tuple(uuid.UUID(item) for item in items) for key, items in value["members"].items()}
    pages = tuple(tuple(SubmissionViewEntry(
        SubmissionViewIdentity(uuid.UUID(row[0]), int(row[1]), datetime.fromisoformat(row[2])),
        row[3], int(row[4]), members.get(row[3], ()), row[5],
    ) for row in page) for page in value["pages"])
    clusters = tuple(tuple(DuplicateClusterPage(**{**cluster,
        "visible_member_ids": tuple(uuid.UUID(item) for item in cluster["visible_member_ids"]),
    }) for cluster in page) for page in value["clusters"])
    return PreparedSubmissionView(pages=pages, clusters=clusters,
        ordered_submission_ids=tuple(uuid.UUID(item) for item in value["ordered"]),
        group_total=value["group_total"], total=value["total"], page_size=value["page_size"],
        document_follow_up_count=value["document_follow_up_count"],
        cluster_boundaries_preserved=value["boundaries"],
        expiry_alerts=tuple(ExpiryAlert(**{**alert, "submission_id": uuid.UUID(alert["submission_id"])}) for alert in value["alerts"]))
