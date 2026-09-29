"""Signed, actor/filter-bound keysets for live MCP read projections."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.application.mcp.credentials import utc


class MCPReadCursor:
    def __init__(self, secret: str, namespace: str):
        if not secret:
            raise ValueError("Cursor signing secret is required")
        self.secret, self.namespace = secret.encode(), namespace.encode() + b"\0"

    def encode(self, state: dict[str, Any]) -> str:
        body = base64.urlsafe_b64encode(json.dumps(state, sort_keys=True).encode()).decode().rstrip("=")
        return body + "." + hmac.new(self.secret, self.namespace + body.encode(), hashlib.sha256).hexdigest()

    def read(self, cursor: str | None, filters: dict[str, Any]) -> dict[str, Any]:
        binding = hashlib.sha256(json.dumps(filters, sort_keys=True, default=str).encode()).hexdigest()
        if not cursor:
            now = datetime.now(UTC)
            return {"v": 1, "binding": binding, "cutoff": now.isoformat(),
                    "expires": (now + timedelta(minutes=30)).isoformat()}
        try:
            if len(cursor) > 2048:
                raise ValueError()
            body, signature = cursor.split(".")
            if not hmac.compare_digest(signature, hmac.new(self.secret, self.namespace + body.encode(), hashlib.sha256).hexdigest()):
                raise ValueError()
            state = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            if state["v"] != 1 or state["binding"] != binding or datetime.fromisoformat(state["expires"]) <= datetime.now(UTC):
                raise ValueError()
            datetime.fromisoformat(state["cutoff"])
            datetime.fromisoformat(state["after_created_at"])
            uuid.UUID(state["after_id"])
            return dict(state)
        except (KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise ValueError("Invalid, expired or differently scoped cursor; restart the query") from exc

    @staticmethod
    def after(state: dict[str, Any]) -> tuple[datetime, uuid.UUID] | None:
        return (datetime.fromisoformat(state["after_created_at"]), uuid.UUID(state["after_id"])) if "after_id" in state else None

    def next(self, state: dict[str, Any], row: dict[str, Any]) -> str:
        return self.encode({**state, "after_created_at": utc(row["created_at"]).isoformat(), "after_id": str(row["id"])})
