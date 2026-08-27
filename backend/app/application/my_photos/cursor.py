"""Tamper-evident, filter- and revision-bound keyset cursors."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass

from app.application.my_photos.errors import MyPhotosInvalidCursor
from app.application.my_photos.states import MatchFilter


@dataclass(frozen=True, slots=True)
class GalleryCursor:
    passenger_id: uuid.UUID
    group_id: uuid.UUID
    revision: int
    match_filter: MatchFilter
    sort_rank: int
    asset_id: uuid.UUID


class GalleryCursorCodec:
    """Sign opaque cursor bodies with an application-secret-derived key."""

    def __init__(self, secret: str) -> None:
        if len(secret.encode("utf-8")) < 16:
            raise ValueError("My Photos cursor signing secret must contain at least 16 bytes")
        self._key = hmac.new(
            secret.encode("utf-8"), b"my-photos-gallery-cursor-v1", hashlib.sha256
        ).digest()

    def encode(self, cursor: GalleryCursor) -> str:
        body = json.dumps(
            {
                "v": 1,
                "p": str(cursor.passenger_id),
                "g": str(cursor.group_id),
                "r": cursor.revision,
                "f": cursor.match_filter,
                "s": cursor.sort_rank,
                "a": str(cursor.asset_id),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signature = hmac.new(self._key, body, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(body + signature).rstrip(b"=").decode("ascii")

    def decode(
        self,
        token: str,
        *,
        passenger_id: uuid.UUID,
        group_id: uuid.UUID,
        revision: int,
        match_filter: MatchFilter,
    ) -> GalleryCursor:
        if not token or len(token) > 768:
            raise MyPhotosInvalidCursor()
        try:
            padded = token + "=" * (-len(token) % 4)
            combined = base64.urlsafe_b64decode(padded.encode("ascii"))
            body, supplied = combined[:-32], combined[-32:]
            expected = hmac.new(self._key, body, hashlib.sha256).digest()
            if len(body) == 0 or not hmac.compare_digest(supplied, expected):
                raise MyPhotosInvalidCursor()
            data = json.loads(body)
            cursor = GalleryCursor(
                passenger_id=uuid.UUID(data["p"]),
                group_id=uuid.UUID(data["g"]),
                revision=int(data["r"]),
                match_filter=data["f"],
                sort_rank=int(data["s"]),
                asset_id=uuid.UUID(data["a"]),
            )
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise MyPhotosInvalidCursor() from exc
        if cursor.passenger_id != passenger_id or cursor.group_id != group_id:
            raise MyPhotosInvalidCursor()
        if cursor.match_filter != match_filter:
            raise MyPhotosInvalidCursor()
        if cursor.revision != revision:
            raise MyPhotosInvalidCursor(stale=True)
        return cursor
