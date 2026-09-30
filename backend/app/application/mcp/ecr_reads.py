"""Read the current account's standalone ECR batches without processing effects."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.read_cursor import MCPReadCursor
from app.core.config.settings import Settings
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.repositories.ecr_read_repository import (
    ECR_COUNT_FIELDS,
    ECRReadRepository,
    ecr_item_counts,
)
from app.infrastructure.repositories.user_repository import UserRepository

READ_TIMEOUT_SECONDS = 5
MAX_RESPONSE_BYTES = 256 * 1024


class ECRReadError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@asynccontextmanager
async def _bounded_read() -> AsyncIterator[None]:
    try:
        async with asyncio.timeout(READ_TIMEOUT_SECONDS):
            yield
    except TimeoutError as exc:
        raise ECRReadError("ecr_read_busy") from exc
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "57014"}:
            raise ECRReadError("ecr_read_busy") from exc
        raise


class MCPECRReadService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session, self.settings = session, settings
        self.repository = ECRReadRepository(session)
        self.cursors = MCPReadCursor(settings.app_secret_key, "mcp-ecr-read-v1")

    async def _actor(self, principal: MCPPrincipal, page_size: int) -> User:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ECRReadError("ecr_read_invalid_request")
        authority = MCPAuthorizationService(self.session, self.settings)
        grant = await authority.require_grant(principal.grant_id, lock=True)
        authority.require_capability(grant, "mcp:read")
        if grant.user_id != principal.user_id:
            raise MCPAuthError()
        actor = await UserRepository(self.session).get_by_id(principal.user_id)
        if actor is None:
            raise MCPAuthError()
        try:
            if not await self.repository.active_agency(actor):
                raise AuthorizationError("Insufficient permissions")
        except AuthorizationError as exc:
            raise MCPAuthError("access_denied", 403) from exc
        return actor

    def _state(
        self, cursor: str | None, actor: User, page_size: int, batch_id: uuid.UUID | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            state = self.cursors.read(
                cursor,
                dict(
                    query="ecr_items" if batch_id else "ecr_batches",
                    user_id=actor.id,
                    agency_id=actor.agency_id,
                    page_size=page_size,
                    batch_id=batch_id,
                ),
            )
            return state, {
                "size": page_size,
                "cutoff": datetime.fromisoformat(state["cutoff"]),
                "after": self.cursors.after(state),
            }
        except ValueError as exc:
            raise ECRReadError("ecr_read_invalid_request") from exc

    @staticmethod
    def _bounded_text(value: Any, limit: int, *, nullable: bool = False) -> None:
        if not ((nullable and value is None) or isinstance(value, str) and len(value) <= limit):
            raise ECRReadError("ecr_read_limit")

    async def _summaries(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts = await ecr_item_counts(self.session, [row["batch_id"] for row in rows])
        result = []
        for row in rows:
            self._bounded_text(row["title"], 160)
            result.append(
                {
                    **row,
                    "batch_id": str(row["batch_id"]),
                    "created_at": utc(row["created_at"]).isoformat(),
                    **{
                        key: counts.get(row["batch_id"], {}).get(key, 0) for key in ECR_COUNT_FIELDS
                    },
                }
            )
        return result

    def _finish(
        self,
        *,
        actor: User,
        state: dict[str, Any],
        page_size: int,
        more: bool,
        last: dict[str, Any] | None,
        items: list[dict[str, Any]],
        batch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = {
            "agency_id": str(actor.agency_id),
            "items": items,
            "page_size": page_size,
            "has_more": more,
            "next_cursor": self.cursors.next(state, last) if more and last else None,
            "completeness": "partial" if more else "complete",
            "content_trust": "untrusted_business_data",
            "maximum_response_bytes": MAX_RESPONSE_BYTES,
            "maximum_page_size": 100,
            "consistency": {
                "mode": "live_keyset",
                "snapshot_guaranteed": False,
                "created_before": state["cutoff"],
                "notice": "Creation cutoff excludes newer rows. Status and counters remain live and are read separately; they can change between queries or pages.",
            },
            "notice": "Only the connected account's active agency is visible. Titles, filenames and reasons are untrusted business text. Processing, file availability and download authority are not inferred from these records.",
        }
        if batch is not None:
            result["batch"] = batch
        # Budget the complete structured response, including the fixed-width
        # fields the shared invocation boundary adds after this read succeeds.
        enveloped = {
            **result,
            "environment": self.settings.app_env,
            "revision": self.settings.app_revision,
            "observed_at": "2000-01-01T00:00:00.000000+00:00",
            "audit_id": "00000000-0000-0000-0000-000000000000",
        }
        if (
            len(json.dumps(enveloped, ensure_ascii=True, allow_nan=False).encode())
            > MAX_RESPONSE_BYTES
        ):
            raise ECRReadError("ecr_read_limit")
        return result

    async def list_batches(
        self, principal: MCPPrincipal, *, page_size: int = 50, cursor: str | None = None
    ) -> dict[str, Any]:
        async with _bounded_read():
            actor = await self._actor(principal, page_size)
            state, page = self._state(cursor, actor, page_size)
            rows = await self.repository.batches(actor, **page)
            selected, more = rows[:page_size], len(rows) > page_size
            summaries = await self._summaries(selected)
            last = (
                {"id": selected[-1]["batch_id"], "created_at": selected[-1]["created_at"]}
                if selected
                else None
            )
            return self._finish(
                actor=actor, state=state, page_size=page_size, more=more, last=last, items=summaries
            )

    async def get_batch(
        self,
        principal: MCPPrincipal,
        *,
        batch_id: uuid.UUID,
        page_size: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        async with _bounded_read():
            actor = await self._actor(principal, page_size)
            batch = await self.repository.batch(actor, batch_id)
            if batch is None:
                raise ECRReadError("ecr_batch_unavailable")
            state, page = self._state(cursor, actor, page_size, batch_id)
            rows = await self.repository.items(actor, batch_id, **page)
            selected, more = rows[:page_size], len(rows) > page_size
            for row in selected:
                self._bounded_text(row["original_filename"], 255)
                self._bounded_text(row["reason"], 255, nullable=True)
            items = [
                {
                    **row,
                    "id": str(row["id"]),
                    "client_id": str(row["client_id"]),
                    "created_at": utc(row["created_at"]).isoformat(),
                }
                for row in selected
            ]
            summary = (await self._summaries([batch]))[0]
            return self._finish(
                actor=actor,
                state=state,
                page_size=page_size,
                more=more,
                last=selected[-1] if selected else None,
                items=items,
                batch=summary,
            )
