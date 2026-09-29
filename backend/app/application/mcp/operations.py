"""Transaction-bound idempotency for explicitly registered database adapters.

No production adapter is registered here. A callback may mutate application rows
or enqueue an existing durable job *in this session*, but may not commit or call
an external provider. This receipt does not make network effects exactly once.
The caller owns commit/rollback; never return a receipt to a client before commit.
Callbacks are trusted, reviewed application code, not a sandbox: raw connection
transaction control, other sessions, network and filesystem effects are forbidden.
Receipt data must be stable and safe to retain; use artifact/entity identifiers,
not credentials, expiring signed URLs or raw document contents.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar, cast
from urllib.parse import urlsplit

from sqlalchemy import event, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, utc
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_models import MCPTokenModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel

NAME = re.compile(r"[a-z][a-z0-9_.]{0,119}\Z")
MAX_JSON_BYTES = 1024 * 1024
_JsonT = TypeVar("_JsonT")
WorkflowStatus = Literal["queued", "running", "succeeded", "failed", "unknown"]
_TRANSITIONS = {
    "queued": {"running", "succeeded", "failed", "unknown"},
    "running": {"running", "succeeded", "failed", "unknown"},
    "unknown": {"unknown", "succeeded", "failed"},
    "succeeded": set(),
    "failed": set(),
}


class MCPOperationError(Exception):
    """Stable, non-sensitive error code for a future reviewed transport adapter."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _json_copy(value: _JsonT) -> _JsonT:
    def validate(item: Any, depth: int = 0) -> None:
        if depth > 48:
            raise ValueError("JSON nesting limit")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("JSON object keys must be strings")
            for child in item.values():
                validate(child, depth + 1)
        elif type(item) is list:
            for child in item:
                validate(child, depth + 1)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError("Only JSON values are supported")

    try:
        validate(value)
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
            raise ValueError("JSON size limit")
        return cast(_JsonT, json.loads(encoded))
    except (TypeError, ValueError, RecursionError, UnicodeError) as exc:
        raise MCPOperationError("invalid_operation_json") from exc


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MCPCreatedEntity:
    entity_type: str
    entity_id: str
    path: str

    def as_dict(self) -> dict[str, str]:
        parsed = urlsplit(self.path)
        if (
            not NAME.fullmatch(self.entity_type)
            or not 1 <= len(self.entity_id) <= 128
            or not self.path.startswith("/")
            or self.path.startswith("//")
            or parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or parsed.query
            or len(self.path) > 512
            or "\\" in self.path
            or any(part in {".", ".."} for part in self.path.split("/"))
            or any(ord(character) < 32 for character in self.path)
        ):
            raise MCPOperationError("invalid_created_entity")
        return {"entity_type": self.entity_type, "entity_id": self.entity_id, "path": self.path}


@dataclass(frozen=True, slots=True)
class MCPDatabaseContext:
    session: AsyncSession
    principal: MCPPrincipal
    operation_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class MCPDatabaseResult:
    data: dict[str, Any]
    status: Literal["queued", "succeeded"] = "succeeded"
    workflow_id: uuid.UUID | None = None
    created_entities: tuple[MCPCreatedEntity, ...] = ()


@dataclass(frozen=True, slots=True)
class MCPDatabaseOperation:
    """Code-owned registration; neither policy nor callback comes from tool input.

    Registration requires separate domain/effect review. The shared policy rejects
    forbidden effects; this helper adds no general-purpose effect allowlist.
    """

    policy: MCPToolPolicy
    mutate: Callable[[MCPDatabaseContext, dict[str, Any]], Awaitable[MCPDatabaseResult]]
    # Reviewed, read-only entity access check; never effects or history writes.
    authorize_receipt: Callable[[MCPDatabaseContext, dict[str, Any]], Awaitable[None]] | None = None


@dataclass(frozen=True, slots=True)
class MCPOperationProgress:
    status: WorkflowStatus
    progress: float
    stage: str
    created_entities: tuple[MCPCreatedEntity, ...] = field(default_factory=tuple)


class MCPOperationService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        operations: Sequence[MCPDatabaseOperation] = (),
    ):
        self.session = session
        self.authorization = MCPAuthorizationService(session, settings)
        self.operations: dict[str, MCPDatabaseOperation] = {}
        for operation in operations:
            operation.policy.validate()
            if (
                not NAME.fullmatch(operation.policy.name)
                or operation.policy.name in self.operations
                or operation.policy.capability in {MCPCapability.READ, MCPCapability.DIAGNOSE}
                or not operation.policy.effects
            ):
                raise ValueError("Invalid database operation registration")
            self.operations[operation.policy.name] = operation

    def _definition(self, name: str) -> MCPDatabaseOperation:
        definition = self.operations.get(name)
        if definition is None:
            raise MCPOperationError("unsupported_operation")
        return definition

    async def _check_receipt_access(
        self,
        definition: MCPDatabaseOperation,
        principal: MCPPrincipal,
        row: MCPOperationModel,
    ) -> None:
        if definition.authorize_receipt is None:
            return
        if row.initial_result is None:
            raise MCPOperationError("operation_receipt_unavailable")

        def reject_commit(_session: Any) -> None:
            raise MCPOperationError("callback_must_not_commit")

        transaction = self.session.sync_session.get_transaction()
        event.listen(self.session.sync_session, "before_commit", reject_commit)
        try:
            await definition.authorize_receipt(
                MCPDatabaseContext(self.session, principal, row.id), _json_copy(row.initial_result)
            )
        finally:
            event.remove(self.session.sync_session, "before_commit", reject_commit)
        if self.session.sync_session.get_transaction() is not transaction:
            raise MCPOperationError("callback_changed_transaction")

    async def _authorize(self, access_token: str, capability: str | None = None) -> MCPPrincipal:
        # Resolve the grant without verify_access's last-used write. The common
        # barrier must acquire control -> grant -> identity before any write.
        if not access_token.startswith("gcmcp_access_") or len(access_token) > 128:
            raise MCPAuthError("invalid_token", 401)
        token = await self.session.scalar(
            select(MCPTokenModel).where(
                MCPTokenModel.token_hash == self.authorization.digest(access_token),
                MCPTokenModel.kind == "access",
            )
        )
        if token is None or utc(token.expires_at) <= datetime.now(UTC):
            raise MCPAuthError("invalid_token", 401)
        grant = await self.authorization.require_grant(token.grant_id, lock=True)
        # A lock can wait behind revocation or identity changes. Check access
        # after acquiring the barrier rather than using an earlier snapshot.
        principal = await self.authorization.verify_access(access_token, capability)
        if grant.user_id != principal.user_id:
            raise MCPAuthError("invalid_token", 401)
        return principal

    async def execute(
        self,
        *,
        access_token: str,
        operation_name: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        definition = self._definition(operation_name)
        if (
            not isinstance(idempotency_key, str)
            or not 16 <= len(idempotency_key) <= 256
            or any(ord(character) < 32 for character in idempotency_key)
        ):
            raise MCPOperationError("invalid_idempotency_key")
        if type(payload) is not dict:
            raise MCPOperationError("invalid_operation_json")
        canonical = _json_copy(payload)
        payload_hash = _digest(
            json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        )
        key_hash = _digest("mcp-operation-v1\0" + idempotency_key)
        capability = definition.policy.capability.value
        principal = await self._authorize(access_token, capability)
        operation_id, now = uuid.uuid4(), datetime.now(UTC)
        dialect = self.session.get_bind().dialect.name
        insert = (
            postgres_insert
            if dialect == "postgresql"
            else sqlite_insert
            if dialect == "sqlite"
            else None
        )
        if insert is None:
            raise MCPOperationError("unsupported_database")
        # PostgreSQL uniqueness waits for a concurrent owner, then the following
        # SELECT gets a fresh READ COMMITTED snapshot and locks the durable row.
        async with self.session.begin_nested():
            await self.session.execute(
                insert(MCPOperationModel)
                .values(
                    id=operation_id,
                    user_id=principal.user_id,
                    initial_grant_id=principal.grant_id,
                    operation_name=operation_name,
                    capability=capability,
                    idempotency_hash=key_hash,
                    payload_hash=payload_hash,
                    initial_result=None,
                    workflow_id=operation_id,
                    status="running",
                    progress=0,
                    stage="applying",
                    revision=0,
                    created_entities=[],
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(
                    index_elements=["user_id", "operation_name", "idempotency_hash"]
                )
            )
            row = await self.session.scalar(
                select(MCPOperationModel)
                .where(
                    MCPOperationModel.user_id == principal.user_id,
                    MCPOperationModel.operation_name == operation_name,
                    MCPOperationModel.idempotency_hash == key_hash,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                # A higher isolation level may require retrying the outer transaction.
                raise MCPOperationError("operation_claim_unavailable")
            await self.authorization.verify_access(access_token, row.capability)
            if row.payload_hash != payload_hash or row.capability != capability:
                raise MCPOperationError("idempotency_conflict")
            if row.id != operation_id:
                if row.initial_result is None:
                    raise MCPOperationError("operation_receipt_unavailable")
                await self._check_receipt_access(definition, principal, row)
                return _json_copy(row.initial_result)

            def reject_commit(_session: Any) -> None:
                raise MCPOperationError("callback_must_not_commit")

            transaction = self.session.sync_session.get_transaction()
            event.listen(self.session.sync_session, "before_commit", reject_commit)
            try:
                result = await definition.mutate(
                    MCPDatabaseContext(self.session, principal, row.id), canonical
                )
            finally:
                event.remove(self.session.sync_session, "before_commit", reject_commit)
            if (
                self.session.sync_session.get_transaction() is not transaction
                or not self.session.in_nested_transaction()
            ):
                raise MCPOperationError("callback_changed_transaction")
            if result.status not in {"queued", "succeeded"} or type(result.data) is not dict:
                raise MCPOperationError("invalid_operation_result")
            row.workflow_id = result.workflow_id or row.id
            row.status, row.stage = result.status, result.status
            row.progress = 1.0 if result.status == "succeeded" else 0.0
            row.revision = 1
            row.created_entities = self._entities(result.created_entities)
            row.updated_at = datetime.now(UTC)
            row.completed_at = row.updated_at if result.status == "succeeded" else None
            row.initial_result = _json_copy(
                {
                    "operation_id": str(row.id),
                    "workflow_id": str(row.workflow_id),
                    "status": row.status,
                    "progress": row.progress,
                    "revision": row.revision,
                    "created_entities": row.created_entities,
                    "data": result.data,
                }
            )
            await self.session.flush()
            await self.authorization.verify_access(access_token, capability)
            return _json_copy(row.initial_result)

    async def inspect(self, *, access_token: str, operation_id: uuid.UUID) -> dict[str, Any]:
        principal = await self._authorize(access_token)
        row = await self.session.scalar(
            select(MCPOperationModel)
            .where(
                MCPOperationModel.id == operation_id,
                MCPOperationModel.user_id == principal.user_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise MCPOperationError("operation_not_found")
        definition = self._definition(row.operation_name)
        await self.authorization.verify_access(access_token, row.capability)
        await self.authorization.verify_access(access_token, definition.policy.capability.value)
        await self._check_receipt_access(definition, principal, row)
        return _json_copy(
            {
                "operation_id": str(row.id),
                "workflow_id": str(row.workflow_id),
                "operation": row.operation_name,
                "status": row.status,
                "progress": row.progress,
                "stage": row.stage,
                "revision": row.revision,
                "created_entities": row.created_entities,
                "created_at": utc(row.created_at).isoformat(),
                "updated_at": utc(row.updated_at).isoformat(),
                "completed_at": utc(row.completed_at).isoformat() if row.completed_at else None,
            }
        )

    @staticmethod
    def _entities(entities: Sequence[MCPCreatedEntity]) -> list[dict[str, str]]:
        if len(entities) > 100:
            raise MCPOperationError("too_many_created_entities")
        links: dict[tuple[str, str], dict[str, str]] = {}
        for entity in entities:
            value = entity.as_dict()
            key = entity.entity_type, entity.entity_id
            if key in links and links[key] != value:
                raise MCPOperationError("created_entity_conflict")
            links[key] = value
        return list(links.values())

    async def record_progress(
        self, *, operation_id: uuid.UUID, expected_revision: int, update: MCPOperationProgress
    ) -> int:
        """Trusted worker hook, not a tool. Caller commits with the domain job update.

        Unknown provider outcomes stay unknown until reconciled; this method
        never schedules a retry, invokes a provider, or authorizes a new action.
        """
        row = await self.session.scalar(
            select(MCPOperationModel)
            .where(
                MCPOperationModel.id == operation_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise MCPOperationError("operation_not_found")
        if row.revision != expected_revision:
            raise MCPOperationError("stale_operation_revision")
        if (
            update.status not in _TRANSITIONS[row.status]
            or not math.isfinite(update.progress)
            or not row.progress <= update.progress <= 1
            or not NAME.fullmatch(update.stage)
            or update.status == "succeeded"
            and update.progress != 1
        ):
            raise MCPOperationError("invalid_workflow_transition")
        links = self._entities(
            [MCPCreatedEntity(**entity) for entity in row.created_entities]
            + list(update.created_entities)
        )
        row.status, row.progress, row.stage = update.status, update.progress, update.stage
        row.created_entities = links
        row.revision += 1
        row.updated_at = datetime.now(UTC)
        row.completed_at = row.updated_at if row.status in {"succeeded", "failed"} else None
        await self.session.flush()
        return row.revision
