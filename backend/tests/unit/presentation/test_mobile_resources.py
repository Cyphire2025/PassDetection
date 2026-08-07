from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Response

from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.storage.minio_repository import ObjectIntegrityMetadata
from app.presentation.api.v1.routes.mobile_resources import (
    _coordinator_roster_revision,
    _distributed_document_source,
    _materialize_personal_document_metadata,
    _mobile_announcement_priority,
    _mobile_document_category,
    _mobile_document_range_start,
    _mobile_manifest_versions,
    _mobile_meal_preference,
    _MobileDocumentSource,
    _passenger_identity,
    _pending_personal_document_response,
    _personal_document_source_by_id,
    _personal_document_source_integrity,
    _safe_mobile_filename,
    _safe_sync_payload,
    _validate_document_signature,
    acknowledge_mobile_sync,
    authorize_mobile_document_download,
    download_mobile_document_content,
    list_mobile_personal_documents,
    list_mobile_sync_changes,
    list_mobile_trips,
    router,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileItineraryDayResponse,
    MobileItineraryItemResponse,
    MobileManifestVersions,
    MobileSyncAcknowledgementRequest,
)


def _claims(role: str = "passenger") -> MobileAccessClaims:
    principal_id = uuid.uuid4()
    return MobileAccessClaims(
        principal_id=principal_id,
        account_id=principal_id,
        principal_type=role,  # type: ignore[arg-type]
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session_generation=1,
        password_change_required=False,
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
    )


def test_mobile_resources_project_domestic_lanes_as_flight_tickets() -> None:
    assert _mobile_document_category("flight_ticket_domestic") == "flight_ticket"
    assert _mobile_document_category("flight_ticket_domestic_arrival") == "flight_ticket"


def test_mobile_resource_keeps_lane_specific_ticket_display_name() -> None:
    source = _distributed_document_source(
        SimpleNamespace(
            id=uuid.uuid4(),
            document_type="flight_ticket_domestic_arrival",
            original_filename="return.pdf",
            content_type="application/pdf",
            storage_key="documents/return.pdf",
            updated_at=datetime.now(tz=UTC),
        ),
        uuid.uuid4(),
        uuid.uuid4(),
    )

    assert source.category == "flight_ticket"
    assert source.display_name == "Domestic Return Flight Ticket"


def test_mobile_resource_routes_are_compact_and_bounded() -> None:
    paths = {route.path for route in router.routes}
    assert paths == {
        "/me",
        "/trips",
        "/trips/{group_id}/manifest",
        "/sync/changes",
        "/sync/ack",
        "/trips/{group_id}/itinerary",
        "/trips/{group_id}/announcements",
        "/trips/{group_id}/common-documents",
        "/trips/{group_id}/documents",
        "/trips/{group_id}/personal-documents",
        "/trips/{group_id}/documents/{document_id}/authorize",
        "/trips/{group_id}/documents/{document_id}/content",
        "/trips/{group_id}/common-documents/{document_id}/content",
        "/trips/{group_id}/personal-documents/{document_id}/content",
        "/trips/{group_id}/room",
        "/trips/{group_id}/meals",
        "/trips/{group_id}/qr",
        "/manager/groups/{group_id}/readiness",
    }


def test_mobile_document_filename_cannot_escape_or_spoof_type() -> None:
    assert (
        _safe_mobile_filename(r"..\..\evil.html\passport.exe", "application/pdf")
        == "passport.pdf"
    )
    assert _safe_mobile_filename("\x00\x1f", "image/jpeg") == "travel-document.jpg"


def test_mobile_document_signature_validation_fails_closed() -> None:
    _validate_document_signature(b"%PDF-1.7\nbody", "application/pdf")
    with pytest.raises(HTTPException) as caught:
        _validate_document_signature(b"<script>alert(1)</script>", "application/pdf")
    assert caught.value.status_code == 503


def test_mobile_document_resume_range_is_strict_and_bounded() -> None:
    assert _mobile_document_range_start(None, 4096) is None
    assert _mobile_document_range_start("bytes=0-", 4096) == 0
    assert _mobile_document_range_start("bytes=2048-", 4096) == 2048

    for invalid in ("bytes=-100", "bytes=0-10", "bytes=0-,20-", "items=1-"):
        with pytest.raises(HTTPException) as caught:
            _mobile_document_range_start(invalid, 4096)
        assert caught.value.status_code == 416

    with pytest.raises(HTTPException) as outside:
        _mobile_document_range_start("bytes=4096-", 4096)
    assert outside.value.status_code == 416
    assert outside.value.headers == {"Content-Range": "bytes */4096"}


@pytest.mark.asyncio
async def test_document_authorization_returns_materialized_integrity_contract() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    document_id = uuid.uuid4()
    identity_id = claims.principal_id
    now = datetime.now(tz=UTC)
    source = _MobileDocumentSource(
        document_id=document_id,
        scope="personal",
        category="passport",
        display_name="Passport",
        safe_filename="passport.jpg",
        content_type="image/jpeg",
        storage_key="private/passport.jpg",
        source_kind="passport_front",
        source_id=uuid.uuid4(),
        source_updated_at=now,
        passenger_identity_id=identity_id,
        passenger_submission_id=uuid.uuid4(),
    )
    trip = SimpleNamespace(
        access=SimpleNamespace(id=uuid.uuid4(), access_generation=3),
    )
    expires_at = now + timedelta(minutes=2)
    request = MagicMock(client=None)

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_resources.MobileAccessPolicy.require_trip_access",
            new=AsyncMock(return_value=trip),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._resolve_mobile_document",
            new=AsyncMock(return_value=(source, 7)),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._document_integrity_metadata",
            new=AsyncMock(return_value=(4096, "a" * 64)),
        ) as integrity,
        patch(
            "app.presentation.api.v1.routes.mobile_resources.create_mobile_document_grant",
            return_value=("t" * 64, expires_at),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._audit_document_access",
            new=AsyncMock(),
        ),
    ):
        response = await authorize_mobile_document_download(
            group_id=group_id,
            document_id=document_id,
            request=request,
            version=7,
            claims=claims,
            session=MagicMock(),
        )

    assert response.size_bytes == 4096
    assert response.checksum_sha256 == "a" * 64
    assert response.content_type == "image/jpeg"
    assert response.content_path.startswith("/api/v1/mobile/")
    assert "private/passport.jpg" not in response.model_dump_json()
    integrity.assert_awaited_once()


class _FakeDocumentStreamStorage:
    def __init__(self) -> None:
        self.get_file_range = AsyncMock(return_value=b"%PDF-1.7\n")
        self.started = 0
        self.closed = 0

    def stream_file(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        async def stream():  # type: ignore[no-untyped-def]
            self.started += 1
            try:
                yield b"document-bytes"
            finally:
                self.closed += 1

        return stream()


def _download_stream_fixture(claims: MobileAccessClaims):
    group_id = uuid.uuid4()
    document_id = uuid.uuid4()
    source = _MobileDocumentSource(
        document_id=document_id,
        scope="common",
        category="itinerary_pdf",
        display_name="Itinerary",
        safe_filename="itinerary.pdf",
        content_type="application/pdf",
        storage_key="gc-app/private/itinerary.pdf",
        source_kind="common",
        source_id=document_id,
        source_updated_at=datetime.now(tz=UTC),
        passenger_identity_id=None,
        passenger_submission_id=None,
    )
    trip = SimpleNamespace(
        access=SimpleNamespace(id=uuid.uuid4(), access_generation=3),
    )
    return group_id, document_id, source, trip


@pytest.mark.asyncio
async def test_queued_document_streams_release_every_request_session_before_waiting() -> None:
    claims = _claims()
    group_id, document_id, source, trip = _download_stream_fixture(claims)
    storage = _FakeDocumentStreamStorage()
    stream_slots = asyncio.Semaphore(0)
    sessions = []
    for _ in range(12):
        session = MagicMock()
        session.commit = AsyncMock()
        session.close = AsyncMock()
        sessions.append(session)
    audit = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_resources.MobileAccessPolicy.require_trip_access",
            new=AsyncMock(return_value=trip),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._resolve_mobile_document",
            new=AsyncMock(return_value=(source, 7)),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._document_integrity_metadata",
            new=AsyncMock(return_value=(4096, "a" * 64)),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources.decode_mobile_document_grant",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources.validate_mobile_document_grant"
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._audit_document_access",
            new=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._MOBILE_DOCUMENT_STREAM_SLOTS",
            stream_slots,
        ),
    ):
        responses = await asyncio.gather(
            *(
                download_mobile_document_content(
                    group_id=group_id,
                    document_id=document_id,
                    request=MagicMock(client=None),
                    version=7,
                    download_token="signed-grant",
                    range_header=None,
                    claims=claims,
                    session=session,
                )
                for session in sessions
            )
        )

        for session in sessions:
            session.commit.assert_awaited_once()
            session.close.assert_awaited_once()
        assert audit.await_count == len(sessions)

        pending_chunks = [
            asyncio.create_task(response.body_iterator.__anext__())
            for response in responses
        ]
        await asyncio.sleep(0)
        assert storage.started == 0
        assert all(not task.done() for task in pending_chunks)

        for _ in pending_chunks:
            stream_slots.release()
        assert await asyncio.gather(*pending_chunks) == [
            b"document-bytes"
        ] * len(pending_chunks)
        for response in responses:
            await response.body_iterator.aclose()

    assert storage.closed == len(sessions)


@pytest.mark.asyncio
async def test_document_stream_cancellation_closes_storage_and_releases_slot() -> None:
    claims = _claims()
    group_id, document_id, source, trip = _download_stream_fixture(claims)
    storage = _FakeDocumentStreamStorage()
    stream_slots = asyncio.Semaphore(1)
    session = MagicMock()
    session.commit = AsyncMock()
    session.close = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_resources.MobileAccessPolicy.require_trip_access",
            new=AsyncMock(return_value=trip),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._resolve_mobile_document",
            new=AsyncMock(return_value=(source, 7)),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._document_integrity_metadata",
            new=AsyncMock(return_value=(4096, "a" * 64)),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources.decode_mobile_document_grant",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources.validate_mobile_document_grant"
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._audit_document_access",
            new=AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._MOBILE_DOCUMENT_STREAM_SLOTS",
            stream_slots,
        ),
    ):
        response = await download_mobile_document_content(
            group_id=group_id,
            document_id=document_id,
            request=MagicMock(client=None),
            version=7,
            download_token="signed-grant",
            range_header="bytes=1024-",
            claims=claims,
            session=session,
        )
        assert await response.body_iterator.__anext__() == b"document-bytes"
        await response.body_iterator.aclose()

        await asyncio.wait_for(stream_slots.acquire(), timeout=0.1)
        stream_slots.release()

    assert storage.closed == 1
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 1024-4095/4096"
    session.commit.assert_awaited_once()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalid_document_grant_fails_before_audit_or_session_release() -> None:
    claims = _claims()
    group_id, document_id, source, trip = _download_stream_fixture(claims)
    session = MagicMock()
    session.commit = AsyncMock()
    session.close = AsyncMock()
    audit = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_resources.MobileAccessPolicy.require_trip_access",
            new=AsyncMock(return_value=trip),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._resolve_mobile_document",
            new=AsyncMock(return_value=(source, 7)),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources.decode_mobile_document_grant",
            return_value=SimpleNamespace(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources.validate_mobile_document_grant",
            side_effect=AuthorizationError("Document download grant is invalid"),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._audit_document_access",
            new=audit,
        ),
    ):
        with pytest.raises(AuthorizationError, match="grant is invalid"):
            await download_mobile_document_content(
                group_id=group_id,
                document_id=document_id,
                request=MagicMock(client=None),
                version=7,
                download_token="invalid-grant",
                range_header=None,
                claims=claims,
                session=session,
            )

    audit.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.close.assert_not_awaited()


def test_itinerary_date_alias_matches_native_contract() -> None:
    item = MobileItineraryItemResponse(
        id=uuid.uuid4(),
        title="Airport reporting",
        sort_order=0,
    )
    response = MobileItineraryDayResponse(
        id=uuid.uuid4(),
        day_number=1,
        trip_date=date(2026, 8, 2),
        title="Arrival",
        sort_order=0,
        items=[item],
    )
    payload = response.model_dump(mode="json", by_alias=True)
    assert payload["date"] == "2026-08-02"
    assert "trip_date" not in payload


def test_sync_payload_never_echoes_unreviewed_fields() -> None:
    payload = _safe_sync_payload(
        {
            "resource_path": "/api/v1/mobile/trips/example/itinerary",
            "itinerary_version_id": str(uuid.uuid4()),
            "passport_number": "SHOULD-NOT-LEAVE-THE-SERVER",
            "storage_key": "private/passport.pdf",
            "nested": {"secret": "value"},
        }
    )
    assert set(payload) == {"resource_path", "itinerary_version_id"}


def test_sync_payload_allows_only_javascript_safe_roster_revision_proof() -> None:
    assert _safe_sync_payload({"roster_revision": 42}) == {"roster_revision": 42}
    assert _safe_sync_payload({"roster_revision": True}) == {}
    assert _safe_sync_payload({"roster_revision": 1 << 53}) == {}


def test_announcement_priority_is_mapped_to_native_contract() -> None:
    assert _mobile_announcement_priority("low") == "normal"
    assert _mobile_announcement_priority("normal") == "normal"
    assert _mobile_announcement_priority("high") == "important"
    assert _mobile_announcement_priority("emergency") == "emergency"


def test_meal_projection_prefers_confirmed_then_staff_and_skips_blanks() -> None:
    assert (
        _mobile_meal_preference(
            {"meal_preference": " Veg "}, {"meal_preference": "Jain"}
        )
        == "Veg"
    )
    assert (
        _mobile_meal_preference(
            {"meal_preference": "   "}, {"meal_preference": " Jain "}
        )
        == "Jain"
    )
    assert _mobile_meal_preference({}, {}) is None


@pytest.mark.asyncio
async def test_passenger_manifest_is_cache_independent_and_uses_resource_revisions() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    trip = SimpleNamespace(
        group=SimpleNamespace(id=group_id),
        access=SimpleNamespace(
            id=uuid.uuid4(),
            manifest_version=1,
            itinerary_version=2,
            common_document_version=3,
            announcement_version=4,
            rooming_version=5,
            meal_version=6,
            qr_version=7,
        ),
        principal_type="passenger",
        passenger_identity=SimpleNamespace(
            id=claims.principal_id,
            passenger_submission_id=uuid.uuid4(),
        ),
    )
    submission = SimpleNamespace(
        updated_at=now,
        image_s3_key="private/passport.jpg",
        passport_back_s3_key=None,
        confirmed_fields={},
        staff_metadata={"meal_preference": "Jain"},
    )

    def first_result(value):  # type: ignore[no-untyped-def]
        result = MagicMock()
        result.first.return_value = value
        return result

    def one_result(value):  # type: ignore[no-untyped-def]
        result = MagicMock()
        result.one.return_value = value
        return result

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            first_result(submission),
            one_result((2, now, now)),
            first_result(submission),
            one_result((2, now, now)),
        ]
    )
    with (
        patch(
            "app.presentation.api.v1.routes.mobile_resources._passenger_rooming_revision",
            new=AsyncMock(return_value=101),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._passenger_qr_revision",
            new=AsyncMock(return_value=202),
        ),
    ):
        before_cache = await _mobile_manifest_versions(
            session, claims=claims, trip=trip
        )
        after_cache = await _mobile_manifest_versions(
            session, claims=claims, trip=trip
        )

    assert before_cache == after_cache
    assert before_cache.personal_documents > 0
    assert before_cache.rooming == 101
    assert before_cache.meals > 0
    assert before_cache.qr == 202
    sql = "\n".join(
        str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        for call in session.execute.await_args_list
    )
    assert "mobile_document_metadata_cache" not in sql


@pytest.mark.asyncio
async def test_coordinator_roster_revision_does_not_track_distributed_documents() -> None:
    claims = _claims("coordinator")
    group_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    trip = SimpleNamespace(group=SimpleNamespace(id=group_id))

    def one_result(value):  # type: ignore[no-untyped-def]
        result = MagicMock()
        result.one.return_value = value
        return result

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            one_result((1500, now)),
            one_result((1400, now, now, now)),
            one_result((1200, now)),
        ]
    )
    revision = await _coordinator_roster_revision(session, claims, trip)

    assert revision > 0
    statements = [
        str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        for call in session.execute.await_args_list
    ]
    sql = "\n".join(statements)
    assert "passport_submissions" in sql
    assert "rooming_assignments" in sql
    assert "attendance_records" in sql
    assert "distributed_documents" not in sql


@pytest.mark.asyncio
async def test_sync_ack_updates_only_live_session_after_version_validation() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    versions = MobileManifestVersions(
        manifest=2,
        itinerary=3,
        common_documents=4,
        personal_documents=5,
        announcements=6,
        rooming=7,
        meals=8,
        qr=9,
        readiness=0,
        roster=0,
    )
    access = SimpleNamespace(
        id=uuid.uuid4(),
        access_generation=11,
        last_successful_sync_at=None,
    )
    trip = SimpleNamespace(access=access, group=SimpleNamespace(id=group_id))
    device = SimpleNamespace(
        selected_gc_group_access_id=None,
        selected_group_id=None,
        last_seen_at=None,
        last_sync_acknowledged_at=None,
    )
    high_water_result = MagicMock()
    high_water_result.scalar_one.return_value = 42
    device_result = MagicMock()
    device_result.scalar_one_or_none.return_value = device
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[high_water_result, device_result])
    session.flush = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_resources.MobileAccessPolicy.require_trip_access",
            new=AsyncMock(return_value=trip),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._mobile_manifest_versions",
            new=AsyncMock(return_value=versions),
        ),
    ):
        response = await acknowledge_mobile_sync(
            body=MobileSyncAcknowledgementRequest(
                trip_id=group_id,
                cursor=42,
                access_generation=11,
                versions=versions,
            ),
            claims=claims,
            session=session,
        )

    assert response.cursor == 42
    assert response.acknowledged_at == access.last_successful_sync_at
    assert device.selected_gc_group_access_id == access.id
    assert device.selected_group_id == group_id
    assert response.acknowledged_at == device.last_seen_at
    assert response.acknowledged_at == device.last_sync_acknowledged_at
    session.flush.assert_awaited_once()
    device_statement = session.execute.await_args_list[1].args[0]
    device_sql = str(device_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "mobile_device_sessions.status = 'active'" in device_sql
    assert claims.session_id.hex in device_sql
    assert "FOR UPDATE" in device_sql


def test_passenger_projection_rejects_manager_trip() -> None:
    with pytest.raises(AuthorizationError, match="Passenger resource"):
        _passenger_identity(
            SimpleNamespace(principal_type="client_manager", passenger_identity=None)
        )


@pytest.mark.asyncio
async def test_pending_personal_documents_remain_visible_until_metadata_is_ready() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    identity = SimpleNamespace(id=claims.principal_id, passenger_submission_id=passenger_id)
    trip = SimpleNamespace(
        group=SimpleNamespace(id=group_id),
        access=SimpleNamespace(id=uuid.uuid4(), agency_id=claims.agency_id),
        principal_type="passenger",
        passenger_identity=identity,
    )
    now = datetime.now(tz=UTC)
    sources = [
        _MobileDocumentSource(
            document_id=uuid.UUID(int=index),
            scope="personal",
            category="visa",
            display_name=f"Visa {index}",
            safe_filename=f"visa-{index}.pdf",
            content_type="application/pdf",
            storage_key=f"private/visa-{index}.pdf",
            source_kind="distributed",
            source_id=uuid.UUID(int=index),
            source_updated_at=now,
            passenger_identity_id=identity.id,
            passenger_submission_id=passenger_id,
        )
        for index in range(1, 5)
    ]
    materialize_mock = AsyncMock()
    with (
        patch(
            "app.presentation.api.v1.routes.mobile_resources.MobileAccessPolicy.require_trip_access",
            new=AsyncMock(return_value=trip),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._personal_document_sources",
            new=AsyncMock(return_value=sources),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._document_cache_by_source",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._materialize_personal_document_metadata",
            new=materialize_mock,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._cache_matches_source",
            new=lambda cache, _source: cache is not None,
        ),
    ):
        first_headers = Response()
        first = await list_mobile_personal_documents(
            group_id=group_id,
            response=first_headers,
            cursor=None,
            limit=10,
            claims=claims,
            session=MagicMock(),
        )
        second_headers = Response()
        second = await list_mobile_personal_documents(
            group_id=group_id,
            response=second_headers,
            cursor=None,
            limit=10,
            claims=claims,
            session=MagicMock(),
        )

    expected_ids = [uuid.UUID(int=index) for index in range(1, 5)]
    assert [item.id for item in first.items] == expected_ids
    assert all(item.metadata_state == "pending" for item in first.items)
    assert all(not item.offline_available for item in first.items)
    assert first_headers.headers["x-gc-metadata-pending"] == "4"
    assert first.next_cursor is None

    assert [item.id for item in second.items] == expected_ids
    assert all(item.metadata_state == "pending" for item in second.items)
    assert all(not item.offline_available for item in second.items)
    assert second_headers.headers["x-gc-metadata-pending"] == "4"
    assert second.next_cursor is None
    materialize_mock.assert_not_awaited()


def _personal_pdf_source(*, size_seed: int = 1) -> _MobileDocumentSource:
    return _MobileDocumentSource(
        document_id=uuid.UUID(int=size_seed),
        scope="personal",
        category="visa",
        display_name="Visa",
        safe_filename="visa.pdf",
        content_type="application/pdf",
        storage_key=f"private/visa-{size_seed}.pdf",
        source_kind="distributed",
        source_id=uuid.UUID(int=size_seed),
        source_updated_at=datetime.now(tz=UTC),
        passenger_identity_id=uuid.uuid4(),
        passenger_submission_id=uuid.uuid4(),
    )


def test_pending_personal_document_advertises_the_next_cached_revision() -> None:
    source = _personal_pdf_source()
    trip = SimpleNamespace(group=SimpleNamespace(id=uuid.uuid4()))
    response = _pending_personal_document_response(
        source,
        trip,
        SimpleNamespace(version=7),
    )

    assert response.version == 8
    assert response.metadata_state == "pending"
    assert response.checksum_sha256 is None


@pytest.mark.asyncio
async def test_materializing_a_replaced_personal_document_uses_the_advertised_revision() -> None:
    source = _personal_pdf_source()
    previous_updated_at = source.source_updated_at - timedelta(minutes=1)
    cache = SimpleNamespace(
        id=source.document_id,
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        gc_group_access_id=uuid.uuid4(),
        passenger_identity_id=source.passenger_identity_id,
        passenger_submission_id=source.passenger_submission_id,
        source_kind=source.source_kind,
        source_id=source.source_id,
        storage_key_hash="key-hash",
        safe_filename=source.safe_filename,
        content_type=source.content_type,
        byte_size=4096,
        checksum_sha256="a" * 64,
        version=7,
        source_updated_at=previous_updated_at,
        created_at=previous_updated_at,
        updated_at=previous_updated_at,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = cache
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    trip = SimpleNamespace(
        group=SimpleNamespace(id=uuid.uuid4()),
        access=SimpleNamespace(id=uuid.uuid4(), agency_id=cache.agency_id),
    )
    identity = SimpleNamespace(
        id=source.passenger_identity_id,
        passenger_submission_id=source.passenger_submission_id,
    )

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_resources._personal_document_source_integrity",
            new=AsyncMock(return_value=(4096, "a" * 64)),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources.hash_mobile_lookup",
            return_value="key-hash",
        ),
    ):
        materialized = await _materialize_personal_document_metadata(
            session,
            trip=trip,
            identity=identity,
            source=source,
        )

    assert materialized.version == 8
    assert materialized.source_updated_at == source.source_updated_at
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_personal_integrity_stored_checksum_avoids_full_body_hash() -> None:
    source = _personal_pdf_source()
    storage = MagicMock()
    storage.stat_file = AsyncMock(
        return_value=ObjectIntegrityMetadata(
            size_bytes=4096,
            checksum_sha256="a" * 64,
            content_type="application/pdf",
        )
    )
    storage.get_file_range = AsyncMock(return_value=b"%PDF-1.7\nheader")
    storage.calculate_file_sha256 = AsyncMock()
    storage.get_file = AsyncMock()

    with patch(
        "app.presentation.api.v1.routes.mobile_resources.MinioStorageRepository",
        return_value=storage,
    ):
        size, checksum = await _personal_document_source_integrity(source)

    assert size == 4096
    assert checksum == "a" * 64
    storage.stat_file.assert_awaited_once_with(source.storage_key)
    storage.get_file_range.assert_awaited_once_with(source.storage_key, start=0, end=15)
    storage.calculate_file_sha256.assert_not_awaited()
    storage.get_file.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_integrity_legacy_source_uses_bounded_hash_primitive() -> None:
    source = _personal_pdf_source(size_seed=2)
    storage = MagicMock()
    storage.stat_file = AsyncMock(
        return_value=ObjectIntegrityMetadata(
            size_bytes=8192,
            checksum_sha256=None,
            content_type="application/pdf",
        )
    )
    storage.get_file_range = AsyncMock(return_value=b"%PDF-1.7\nheader")
    storage.calculate_file_sha256 = AsyncMock(return_value="b" * 64)

    with patch(
        "app.presentation.api.v1.routes.mobile_resources.MinioStorageRepository",
        return_value=storage,
    ):
        size, checksum = await _personal_document_source_integrity(source)

    assert (size, checksum) == (8192, "b" * 64)
    storage.calculate_file_sha256.assert_awaited_once_with(
        source.storage_key,
        expected_bytes=8192,
    )


@pytest.mark.asyncio
async def test_personal_integrity_rejects_oversize_before_body_read() -> None:
    source = _personal_pdf_source(size_seed=3)
    storage = MagicMock()
    storage.stat_file = AsyncMock(
        return_value=ObjectIntegrityMetadata(
            size_bytes=10**12,
            checksum_sha256="c" * 64,
            content_type="application/pdf",
        )
    )
    storage.get_file_range = AsyncMock()
    storage.calculate_file_sha256 = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_resources.MinioStorageRepository",
            return_value=storage,
        ),
        pytest.raises(HTTPException) as caught,
    ):
        await _personal_document_source_integrity(source)

    assert caught.value.status_code == 413
    storage.get_file_range.assert_not_awaited()
    storage.calculate_file_sha256.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_document_pages_reach_owned_documents_beyond_legacy_cap() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    identity = SimpleNamespace(id=claims.principal_id, passenger_submission_id=passenger_id)
    trip = SimpleNamespace(
        group=SimpleNamespace(id=group_id),
        access=SimpleNamespace(id=uuid.uuid4(), agency_id=claims.agency_id),
        principal_type="passenger",
        passenger_identity=identity,
    )
    now = datetime.now(tz=UTC)
    submission = SimpleNamespace(
        id=passenger_id,
        image_s3_key=None,
        passport_back_s3_key=None,
        updated_at=now,
    )
    documents = [
        SimpleNamespace(
            id=uuid.UUID(int=index),
            content_type="application/pdf",
            document_type="visa",
            original_filename=f"visa-{index}.pdf",
            storage_key=f"private/visa-{index}.pdf",
            updated_at=now,
        )
        for index in range(1, 251)
    ]

    def scalar_result(value):  # type: ignore[no-untyped-def]
        result = MagicMock()
        result.scalar_one_or_none.return_value = value
        return result

    def scalars_result(values):  # type: ignore[no-untyped-def]
        result = MagicMock()
        result.scalars.return_value = values
        return result

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            scalar_result(submission),
            scalars_result(documents[:201]),
            scalar_result(submission),
            scalars_result(documents[200:]),
        ]
    )

    async def ready_caches(*_args, sources, **_kwargs):  # type: ignore[no-untyped-def]
        return {
            (source.source_kind, source.source_id): SimpleNamespace(
                group_id=group_id,
                byte_size=1024,
                version=1,
                checksum_sha256="a" * 64,
                updated_at=now,
            )
            for source in sources
        }

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_resources.MobileAccessPolicy.require_trip_access",
            new=AsyncMock(return_value=trip),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._document_cache_by_source",
            new=AsyncMock(side_effect=ready_caches),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_resources._cache_matches_source",
            new=lambda cache, _source: cache is not None,
        ),
    ):
        first = await list_mobile_personal_documents(
            group_id=group_id,
            response=Response(),
            cursor=None,
            limit=200,
            claims=claims,
            session=session,
        )
        assert first.next_cursor == str(uuid.UUID(int=200))
        second = await list_mobile_personal_documents(
            group_id=group_id,
            response=Response(),
            cursor=uuid.UUID(first.next_cursor),
            limit=200,
            claims=claims,
            session=session,
        )

    combined_ids = [item.id for item in first.items + second.items]
    assert combined_ids == [uuid.UUID(int=index) for index in range(1, 251)]
    assert len(set(combined_ids)) == 250
    assert second.next_cursor is None

    first_page_statement = session.execute.await_args_list[1].args[0]
    second_page_statement = session.execute.await_args_list[3].args[0]
    first_page_sql = str(
        first_page_statement.compile(compile_kwargs={"literal_binds": True})
    )
    second_page_sql = str(
        second_page_statement.compile(compile_kwargs={"literal_binds": True})
    )
    assert "ORDER BY distributed_documents.id" in first_page_sql
    assert "LIMIT 201" in first_page_sql
    assert "distributed_documents.id >" in second_page_sql
    assert "distributed_documents.agency_id" in second_page_sql
    assert "distributed_documents.group_id" in second_page_sql
    assert "distributed_documents.passenger_id" in second_page_sql
    assert "document_whatsapp_deliveries" in first_page_sql
    assert "document_whatsapp_deliveries.status IN" in first_page_sql
    assert "'submitted', 'sent', 'delivered', 'read'" in first_page_sql


@pytest.mark.asyncio
async def test_personal_document_exact_lookup_is_owned_and_not_page_limited() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    identity = SimpleNamespace(id=claims.principal_id, passenger_submission_id=passenger_id)
    trip = SimpleNamespace(
        group=SimpleNamespace(id=group_id),
        access=SimpleNamespace(id=uuid.uuid4(), agency_id=claims.agency_id),
        principal_type="passenger",
        passenger_identity=identity,
    )
    now = datetime.now(tz=UTC)
    submission = SimpleNamespace(
        id=passenger_id,
        image_s3_key=None,
        passport_back_s3_key=None,
        updated_at=now,
    )
    target_id = uuid.UUID(int=250)
    document = SimpleNamespace(
        id=target_id,
        content_type="application/pdf",
        document_type="visa",
        original_filename="visa-250.pdf",
        storage_key="private/visa-250.pdf",
        updated_at=now,
    )

    submission_result = MagicMock()
    submission_result.scalar_one_or_none.return_value = submission
    document_result = MagicMock()
    document_result.scalar_one_or_none.return_value = document
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[submission_result, document_result])

    source = await _personal_document_source_by_id(
        session,
        claims,
        trip,
        target_id,
    )

    assert source is not None
    assert source.document_id == target_id
    statement = session.execute.await_args_list[1].args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "distributed_documents.id =" in sql
    assert "distributed_documents.agency_id" in sql
    assert "distributed_documents.group_id" in sql
    assert "distributed_documents.passenger_id" in sql
    assert "document_whatsapp_deliveries" in sql
    assert "document_whatsapp_deliveries.status IN" in sql
    assert "LIMIT" not in sql


@pytest.mark.asyncio
async def test_sync_cursor_advances_across_expired_or_invisible_journal_gaps() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    trip = SimpleNamespace(
        group=SimpleNamespace(id=group_id),
        access=SimpleNamespace(id=uuid.uuid4(), access_generation=3),
        principal_type="passenger",
        passenger_identity=SimpleNamespace(id=claims.principal_id),
    )
    high_water_result = MagicMock()
    high_water_result.scalar_one.return_value = 17
    page_result = MagicMock()
    page_result.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[high_water_result, page_result])

    with patch(
        "app.presentation.api.v1.routes.mobile_resources.MobileAccessPolicy.require_trip_access",
        new=AsyncMock(return_value=trip),
    ):
        response = await list_mobile_sync_changes(
            trip_id=group_id,
            cursor=0,
            limit=25,
            claims=claims,
            session=session,
        )

    assert response.changes == []
    assert response.next_cursor == 17
    assert response.has_more is False

    high_water_statement = session.execute.await_args_list[0].args[0]
    page_statement = session.execute.await_args_list[1].args[0]
    high_water_sql = str(
        high_water_statement.compile(compile_kwargs={"literal_binds": True})
    )
    page_sql = str(page_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "max(mobile_sync_changes.sequence)" in high_water_sql
    assert "mobile_sync_changes.access_generation = 3" in high_water_sql
    assert "mobile_sync_changes.expires_at" not in high_water_sql
    assert "mobile_sync_changes.sequence <= 17" in page_sql
    assert "mobile_sync_changes.expires_at" in page_sql
    assert "mobile_sync_changes.audience IN ('all', 'passenger')" in page_sql
    assert claims.principal_id.hex in page_sql


@pytest.mark.asyncio
async def test_passenger_trip_list_query_contains_all_fail_closed_gates() -> None:
    claims = _claims()
    result = MagicMock()
    result.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    response = await list_mobile_trips(
        cursor=None,
        limit=25,
        claims=claims,
        session=session,
    )

    assert response.items == []
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "gc_group_access.agency_id" in sql
    assert "client_groups.agency_id" in sql
    assert "client_groups.status IN ('active', 'closed')" in sql
    assert "gc_group_access.is_enabled IS true" in sql
    assert "gc_group_access.passenger_access_enabled IS true" in sql
    assert "mobile_passenger_identities.id" in sql
    assert "mobile_passenger_session_identities.session_id" in sql
    assert claims.session_id.hex in sql
    assert "mobile_passenger_session_identities.agency_id" in sql
    assert "mobile_passenger_identities.claim_generation = " in sql
    assert "mobile_passenger_session_identities.identity_claim_generation" in sql
    assert "mobile_passenger_identities.revoked_at IS NULL" in sql
    assert "gc_group_access.access_starts_at" in sql
    assert "gc_group_access.access_expires_at" in sql


@pytest.mark.asyncio
async def test_passenger_trip_list_returns_every_live_identity_authorized_for_session() -> None:
    claims = _claims()

    def access() -> SimpleNamespace:
        return SimpleNamespace(
            access_generation=2,
            itinerary_version=3,
            common_document_version=4,
            announcement_version=5,
        )

    first_group = SimpleNamespace(
        id=uuid.uuid4(),
        name="First trip",
        destination="Vietnam",
        travel_date=date(2026, 8, 10),
        return_date=date(2026, 8, 15),
    )
    second_group = SimpleNamespace(
        id=uuid.uuid4(),
        name="Second trip",
        destination="Thailand",
        travel_date=date(2026, 9, 10),
        return_date=date(2026, 9, 15),
    )
    result = MagicMock()
    result.all.return_value = [
        (access(), first_group, uuid.uuid4()),
        (access(), second_group, uuid.uuid4()),
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    response = await list_mobile_trips(
        cursor=None,
        limit=25,
        claims=claims,
        session=session,
    )

    assert [item.id for item in response.items] == [first_group.id, second_group.id]
    assert all(item.role == "passenger" for item in response.items)
