from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    AttendanceDiscardTombstoneModel,
    AttendanceRuntimeRegistrationModel,
)
from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutAssignmentCheckpoint,
    AttendanceCloseoutCounts,
    classify_attendance_closeout,
)
from app.infrastructure.repositories.attendance_discard_repository import (
    AttendanceDiscardInput,
    AttendanceDiscardRepository,
)
from app.infrastructure.repositories.attendance_runtime_repository import (
    AttendanceRuntimeError,
    AttendanceRuntimeRepository,
)
from app.presentation.api.v1.schemas.attendance_runtime_schemas import (
    AttendanceDiscardBatchRequest,
    AttendanceDiscardItemRequest,
)
from app.presentation.security.attendance_runtime import (
    parse_attendance_runtime_cookie,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
AGENCY_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
OTHER_AGENCY_ID = uuid.UUID("10000000-0000-0000-0000-000000000002")
COORDINATOR_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
GROUP_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
SESSION_ID = uuid.UUID("40000000-0000-0000-0000-000000000001")
RUNTIME_ID = uuid.UUID("50000000-0000-0000-0000-000000000001")
EVENT_ID = uuid.UUID("60000000-0000-0000-0000-000000000001")
SCAN_REFERENCE = hashlib.sha256(b"sensitive-qr-fixture-never-persisted").hexdigest()


class _Scalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def __iter__(self) -> Iterator[object]:
        return iter(self._values)

    def all(self) -> list[object]:
        return self._values


class _Result:
    def __init__(
        self,
        *,
        scalar: object | None = None,
        scalars: list[object] | None = None,
    ) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self) -> object | None:
        return self._scalar

    def scalar_one(self) -> object:
        assert self._scalar is not None
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._scalars)


class _Session:
    def __init__(self, results: list[_Result]) -> None:
        self._results = results
        self.statements: list[object] = []
        self.flush_count = 0

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        if not self._results:
            return _Result()
        return self._results.pop(0)

    async def flush(self) -> None:
        self.flush_count += 1


def _runtime(*, agency_id: uuid.UUID = AGENCY_ID) -> AttendanceRuntimeRegistrationModel:
    return AttendanceRuntimeRegistrationModel(
        id=RUNTIME_ID,
        agency_id=agency_id,
        coordinator_user_id=COORDINATOR_ID,
        runtime_kind="pwa",
        runtime_identifier_hash="a" * 64,
        status="active",
        registered_at=NOW,
        last_seen_at=NOW,
        expires_at=NOW + timedelta(days=30),
        created_at=NOW,
        updated_at=NOW,
    )


def _persisted_discard(
    *,
    agency_id: uuid.UUID = AGENCY_ID,
    scan_reference: str = SCAN_REFERENCE,
) -> AttendanceDiscardTombstoneModel:
    return AttendanceDiscardTombstoneModel(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=GROUP_ID,
        session_id=SESSION_ID,
        coordinator_user_id=COORDINATOR_ID,
        runtime_registration_id=RUNTIME_ID,
        discard_event_id=EVENT_ID,
        scan_reference=scan_reference,
        reason_category="server_terminal_rejection",
        captured_at=NOW - timedelta(minutes=2),
        discarded_at=NOW - timedelta(minutes=1),
        received_at=NOW,
        status="accepted",
        retention_expires_at=NOW + timedelta(days=365),
        updated_at=NOW,
    )


def _discard_input(
    *,
    scan_reference: str = SCAN_REFERENCE,
    discarded_at: datetime = NOW - timedelta(minutes=1),
    captured_at: datetime | None = NOW - timedelta(minutes=2),
) -> AttendanceDiscardInput:
    return AttendanceDiscardInput(
        discard_event_id=EVENT_ID,
        scan_reference=scan_reference,
        reason_category="server_terminal_rejection",
        captured_at=captured_at,
        discarded_at=discarded_at,
    )


@pytest.mark.asyncio
async def test_browser_runtime_stores_only_a_purpose_bound_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_secret = "runtime-cookie-secret-that-never-enters-the-database"
    session = _Session([_Result(scalar=_runtime())])
    monkeypatch.setattr(
        "app.infrastructure.repositories.attendance_runtime_repository.secrets.token_urlsafe",
        lambda _size: raw_secret,
    )

    issued = await AttendanceRuntimeRepository(cast(AsyncSession, session)).issue_browser_runtime(
        agency_id=AGENCY_ID,
        coordinator_user_id=COORDINATOR_ID,
        runtime_kind="pwa",
        expires_at=NOW + timedelta(days=30),
        now=NOW,
    )

    assert issued.cookie_secret == raw_secret
    statement = session.statements[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert raw_secret not in str(compiled)
    assert raw_secret not in repr(compiled.params)
    identifier_hash = next(
        value for key, value in compiled.params.items() if "runtime_identifier_hash" in key
    )
    assert isinstance(identifier_hash, str) and len(identifier_hash) == 64
    assert session.flush_count == 1


@pytest.mark.asyncio
async def test_runtime_resolution_is_tenant_user_kind_expiry_scoped_and_locked() -> None:
    session = _Session([_Result(scalar=_runtime())])

    resolved = await AttendanceRuntimeRepository(
        cast(AsyncSession, session)
    ).resolve_browser_runtime(
        agency_id=AGENCY_ID,
        coordinator_user_id=COORDINATOR_ID,
        cookie_secret="opaque-cookie-secret-12345678901234567890",
        runtime_kind="pwa",
        now=NOW,
        lock=True,
    )

    assert resolved.id == RUNTIME_ID
    statement = session.statements[0]
    compiled = str(statement.compile(dialect=postgresql.dialect())).lower()
    assert "attendance_runtime_registrations.agency_id" in compiled
    assert "attendance_runtime_registrations.coordinator_user_id" in compiled
    assert "attendance_runtime_registrations.runtime_kind" in compiled
    assert "attendance_runtime_registrations.runtime_identifier_hash" in compiled
    assert "attendance_runtime_registrations.status" in compiled
    assert "attendance_runtime_registrations.expires_at" in compiled
    assert "for update" in compiled


@pytest.mark.asyncio
async def test_expired_runtime_registration_fails_before_database_access() -> None:
    session = _Session([])

    with pytest.raises(AttendanceRuntimeError, match="expiry is invalid"):
        await AttendanceRuntimeRepository(cast(AsyncSession, session)).register(
            agency_id=AGENCY_ID,
            coordinator_user_id=COORDINATOR_ID,
            runtime_kind="pwa",
            runtime_identifier="opaque",
            expires_at=NOW,
            now=NOW,
        )

    assert session.statements == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("inserted_ids", "expected_status"),
    [([EVENT_ID], "accepted"), ([], "already_applied")],
)
async def test_discard_delivery_is_idempotent_and_marks_runtime_participation(
    inserted_ids: list[uuid.UUID],
    expected_status: str,
) -> None:
    session = _Session(
        [
            _Result(scalars=[cast(object, event_id) for event_id in inserted_ids]),
            _Result(scalars=[_persisted_discard()]),
            _Result(),
        ]
    )

    result = await AttendanceDiscardRepository(cast(AsyncSession, session)).record_batch(
        agency_id=AGENCY_ID,
        group_id=GROUP_ID,
        session_id=SESSION_ID,
        coordinator_user_id=COORDINATOR_ID,
        runtime_registration_id=RUNTIME_ID,
        items=(_discard_input(),),
        retention_days=365,
        now=NOW,
    )

    assert result[0].status == expected_status
    assert result[0].discard_event_id == EVENT_ID
    assert len(session.statements) == 3
    persistence_query = str(session.statements[1].compile(dialect=postgresql.dialect())).lower()
    assert "attendance_discard_tombstones.agency_id" in persistence_query
    assert "attendance_discard_tombstones.coordinator_user_id" in persistence_query
    assert "attendance_discard_tombstones.discard_event_id" in persistence_query
    participation_statement = str(
        session.statements[2].compile(dialect=postgresql.dialect())
    ).lower()
    assert "attendance_session_runtime_participants" in participation_statement
    assert session.flush_count == 2


@pytest.mark.asyncio
async def test_reused_discard_event_with_different_evidence_is_a_conflict() -> None:
    session = _Session(
        [
            _Result(scalars=[]),
            _Result(scalars=[_persisted_discard(scan_reference="b" * 64)]),
        ]
    )

    with pytest.raises(ValueError, match="idempotency conflict"):
        await AttendanceDiscardRepository(cast(AsyncSession, session)).record_batch(
            agency_id=AGENCY_ID,
            group_id=GROUP_ID,
            session_id=SESSION_ID,
            coordinator_user_id=COORDINATOR_ID,
            runtime_registration_id=RUNTIME_ID,
            items=(_discard_input(),),
            retention_days=365,
            now=NOW,
        )

    assert len(session.statements) == 2
    assert session.flush_count == 0


@pytest.mark.asyncio
async def test_cross_tenant_idempotency_row_is_never_accepted_as_the_callers_receipt() -> None:
    session = _Session(
        [
            _Result(scalars=[]),
            # A duplicate identifier belonging to another tenant is excluded
            # by the scoped receipt query and therefore cannot be acknowledged.
            _Result(scalars=[]),
        ]
    )

    with pytest.raises(RuntimeError, match="persistence was incomplete"):
        await AttendanceDiscardRepository(cast(AsyncSession, session)).record_batch(
            agency_id=AGENCY_ID,
            group_id=GROUP_ID,
            session_id=SESSION_ID,
            coordinator_user_id=COORDINATOR_ID,
            runtime_registration_id=RUNTIME_ID,
            items=(_discard_input(),),
            retention_days=365,
            now=NOW,
        )

    compiled = session.statements[1].compile(dialect=postgresql.dialect())
    assert AGENCY_ID in compiled.params.values()
    assert OTHER_AGENCY_ID not in compiled.params.values()
    assert COORDINATOR_ID in compiled.params.values()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "item",
    [
        _discard_input(scan_reference="not-a-hash"),
        _discard_input(discarded_at=NOW + timedelta(minutes=6)),
        _discard_input(captured_at=NOW, discarded_at=NOW - timedelta(seconds=1)),
        _discard_input(discarded_at=datetime(2026, 8, 23, 11, 59)),
    ],
)
async def test_invalid_discard_evidence_fails_before_persistence(
    item: AttendanceDiscardInput,
) -> None:
    session = _Session([])

    with pytest.raises(ValueError):
        await AttendanceDiscardRepository(cast(AsyncSession, session)).record_batch(
            agency_id=AGENCY_ID,
            group_id=GROUP_ID,
            session_id=SESSION_ID,
            coordinator_user_id=COORDINATOR_ID,
            runtime_registration_id=RUNTIME_ID,
            items=(item,),
            retention_days=365,
            now=NOW,
        )

    assert session.statements == []


def test_discard_request_normalizes_hash_prefix_and_rejects_raw_qr_fields() -> None:
    request = AttendanceDiscardItemRequest(
        discard_event_id=EVENT_ID,
        group_id=GROUP_ID,
        session_id=SESSION_ID,
        installation_runtime_id="local-installation-hint",
        scan_reference=f"sha256:{SCAN_REFERENCE}",
        reason_category="server_terminal_rejection",
        captured_at=NOW - timedelta(minutes=2),
        discarded_at=NOW - timedelta(minutes=1),
    )
    assert request.scan_reference == SCAN_REFERENCE

    with pytest.raises(ValidationError, match="Extra inputs"):
        AttendanceDiscardItemRequest.model_validate(
            {
                **request.model_dump(),
                "raw_qr": "must-never-cross-the-discard-boundary",
            }
        )

    with pytest.raises(ValidationError, match="unique"):
        AttendanceDiscardBatchRequest(items=[request, request])


def test_runtime_cookie_parser_is_strict_and_never_accepts_client_runtime_ids() -> None:
    secret = "x" * 43
    assert parse_attendance_runtime_cookie(f"v1.pwa.{secret}") == ("pwa", secret)
    assert parse_attendance_runtime_cookie(f"v1.webview.{secret}") == ("webview", secret)
    for malformed in (
        None,
        "",
        f"v2.pwa.{secret}",
        f"v1.native_mobile.{secret}",
        "v1.pwa.short",
        f"v1.pwa.{secret}.extra",
    ):
        assert parse_attendance_runtime_cookie(malformed) is None


def test_one_clean_runtime_cannot_hide_another_runtime_with_pending_work() -> None:
    clean_runtime_id = uuid.UUID("50000000-0000-0000-0000-000000000001")
    pending_runtime_id = uuid.UUID("50000000-0000-0000-0000-000000000002")
    assignments = [
        AttendanceCloseoutAssignmentCheckpoint(
            coordinator_id=COORDINATOR_ID,
            coordinator_name="Shared Account Coordinator",
            assigned_at=NOW - timedelta(hours=1),
            reported_at=NOW - timedelta(seconds=3),
            counts=AttendanceCloseoutCounts(0, 0, 0, 0, 0, None),
            runtime_id=clean_runtime_id,
            runtime_kind="native_mobile",
        ),
        AttendanceCloseoutAssignmentCheckpoint(
            coordinator_id=COORDINATOR_ID,
            coordinator_name="Shared Account Coordinator",
            assigned_at=NOW - timedelta(hours=1),
            reported_at=NOW - timedelta(seconds=2),
            counts=AttendanceCloseoutCounts(7, 0, 0, 0, 0, 90),
            runtime_id=pending_runtime_id,
            runtime_kind="native_mobile",
        ),
    ]

    status = classify_attendance_closeout(
        assignments,
        activity_valid_after=NOW - timedelta(hours=1),
        now=NOW,
    )

    assert status.ready is False
    assert status.active_assignment_count == 2
    assert status.ready_assignment_count == 1
    assert status.blocked_assignment_count == 1
    assert status.unresolved_count == 7
    assert {item.runtime_id for item in status.coordinators} == {
        clean_runtime_id,
        pending_runtime_id,
    }


def test_closeout_requires_clean_recent_evidence_from_every_participating_runtime() -> None:
    runtime_ids = (uuid.uuid4(), uuid.uuid4())
    status = classify_attendance_closeout(
        [
            AttendanceCloseoutAssignmentCheckpoint(
                coordinator_id=COORDINATOR_ID,
                coordinator_name="Shared Account Coordinator",
                assigned_at=NOW - timedelta(hours=1),
                reported_at=NOW - timedelta(seconds=index + 1),
                counts=AttendanceCloseoutCounts(0, 0, 0, 0, 0, None),
                runtime_id=runtime_id,
                runtime_kind="native_mobile",
            )
            for index, runtime_id in enumerate(runtime_ids)
        ],
        activity_valid_after=NOW - timedelta(hours=1),
        now=NOW,
    )

    assert status.ready is True
    assert status.active_assignment_count == 2
    assert status.ready_assignment_count == 2
