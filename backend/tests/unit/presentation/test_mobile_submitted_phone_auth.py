from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.application.mobile.passenger_phone_authority import authoritative_submission_phone
from app.core.security.mobile_jwt import hash_mobile_lookup, hash_mobile_otp_code
from app.presentation.api.v1.routes import mobile_auth as routes
from app.presentation.api.v1.routes.mobile_auth_phone_support import (
    challenge_phone,
    submitted_phone_rows,
    unavailable_trip_status,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileDeviceInput,
    MobileOTPRequest,
    MobileOTPVerifyRequest,
    MobileOTPVerifyResponse,
)

PHONE = "+919876543210"


def submission(**changes):
    values = dict(
        id=uuid.uuid4(), agency_id=uuid.uuid4(), group_id=uuid.uuid4(),
        client_phone=PHONE, status="submitted", client_reviewed_at=datetime.now(UTC),
        image_s3_key="passports/collected.jpg", confidence_score={}, staff_metadata={},
    )
    return SimpleNamespace(**(values | changes))


def access(**changes):
    return SimpleNamespace(**(dict(
        is_enabled=True, passenger_access_enabled=True, revoked_at=None,
        access_starts_at=None, access_expires_at=None,
    ) | changes))


def request():
    return Request({"type": "http", "method": "POST", "path": "/mobile/auth/otp", "headers": []})


@pytest.fixture
def auth_environment(monkeypatch):
    mobile = SimpleNamespace(
        enabled=True, otp_development_code=None, otp_provider="whatsapp",
        otp_ttl_seconds=300, otp_max_attempts=5, otp_resend_cooldown_seconds=60,
    )
    monkeypatch.setattr(routes, "get_settings", lambda: SimpleNamespace(mobile=mobile, whatsapp_phone_number_id="test"))
    monkeypatch.setattr(routes.MobileOTPRateLimiter, "consume", AsyncMock())
    monkeypatch.setattr(routes, "_complete_neutral_otp_timing", AsyncMock())
    monkeypatch.setattr(routes, "_reconcile_phone_candidate_groups", AsyncMock())
    monkeypatch.setattr(routes, "_eligible_passenger_identities", AsyncMock(return_value=[]))
    monkeypatch.setattr(routes, "bind_source_provider_message", AsyncMock())
    monkeypatch.setattr(routes, "AuditLogRepository", lambda _: SimpleNamespace(record=AsyncMock()))
    provider = SimpleNamespace(send_code=AsyncMock(return_value="wamid.synthetic"))
    monkeypatch.setattr(routes, "get_otp_provider", lambda: provider)
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = MagicMock(execute=AsyncMock(return_value=result), flush=AsyncMock(), commit=AsyncMock())
    return session, provider


@pytest.mark.parametrize("status", ["submitted", "needs_review", "ai_approved", "staff_approved", "client_submitted", "confirmed"])
def test_completed_collection_statuses_authorize_without_staff_approval(status):
    assert authoritative_submission_phone(submission(status=status, image_s3_key="")) == PHONE


@pytest.mark.parametrize("changes", [
    {"status": "ready_for_client_review"}, {"client_reviewed_at": None},
    {"client_phone": None}, {"confidence_score": {"source": "excel_import"}},
    {"image_s3_key": "excel-imports/row.placeholder"},
])
def test_drafts_and_imported_numbers_are_not_collection_authority(changes):
    assert authoritative_submission_phone(submission(**changes)) is None


def test_explicit_public_completion_can_supersede_legacy_import_provenance():
    assert authoritative_submission_phone(submission(
        confidence_score={"source": "excel_import"}, staff_metadata={"client_collection_submitted": "public_group_link_v1"},
    )) == PHONE


@pytest.mark.asyncio
@pytest.mark.parametrize("is_submitted", [False, True])
async def test_send_uses_submission_presence_even_without_active_gc_identity(auth_environment, monkeypatch, is_submitted):
    session, provider = auth_environment
    rows = [(submission(), SimpleNamespace(), None)] if is_submitted else []
    monkeypatch.setattr(routes, "submitted_phone_rows", AsyncMock(return_value=rows))
    if not is_submitted:
        # Even an existing legacy roster identity must never enable a send.
        monkeypatch.setattr(routes, "_eligible_passenger_identities", AsyncMock(return_value=[
            (SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4()), None, None),
        ]))
    response = await routes.request_passenger_otp(MobileOTPRequest(phone_number=PHONE), request(), session)
    assert response.accepted is True
    assert set(response.model_dump()) == {"accepted", "challenge_id", "expires_in_seconds", "resend_after_seconds"}
    assert provider.send_code.await_count == int(is_submitted)
    if is_submitted:
        assert provider.send_code.await_args.kwargs["normalized_phone"] == PHONE


@pytest.mark.parametrize(("settings", "expected"), [
    (None, "trip_not_active"), (access(is_enabled=False), "trip_not_active"),
    (access(passenger_access_enabled=False), "trip_not_active"),
    (access(access_starts_at=datetime.now(UTC) + timedelta(days=1)), "trip_starts_later"),
    (access(access_expires_at=datetime.now(UTC) - timedelta(days=1)), "trip_access_ended"),
    (access(), None),
])
def test_guidance_is_generic_and_distinguishes_access_window(settings, expected):
    assert unavailable_trip_status([(submission(), SimpleNamespace(name="Must stay private"), settings)]) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("correct_code", [False, True])
async def test_inactive_guidance_requires_correct_phone_ownership_proof(auth_environment, monkeypatch, correct_code):
    session, _provider = auth_environment
    challenge_id = uuid.uuid4()
    challenge = SimpleNamespace(
        id=challenge_id, status="pending", expires_at=datetime.now(UTC) + timedelta(minutes=5),
        code_hash=hash_mobile_otp_code(challenge_id, "123456"), attempt_count=0, max_attempts=5,
        phone_lookup_hash=hash_mobile_lookup(PHONE, purpose="passenger-phone"),
    )
    monkeypatch.setattr(routes, "_locked_challenge", AsyncMock(return_value=challenge))
    lookup = AsyncMock(return_value=[(submission(), SimpleNamespace(), None)])
    monkeypatch.setattr(routes, "submitted_phone_rows", lookup)
    issue = AsyncMock()
    monkeypatch.setattr(routes, "_issue_passenger_session", issue)
    body = MobileOTPVerifyRequest(
        challenge_id=challenge_id, code="123456" if correct_code else "654321", phone_number=PHONE,
        device=MobileDeviceInput(installation_id="synthetic-installation-123", platform="android", app_version="1.0.4"),
    )
    if correct_code:
        response = await routes.verify_passenger_otp(body, request(), session)
        assert response.model_dump() == {"status": "trip_not_active", "claims": [], "tokens": None}
        assert challenge.status == "consumed"
    else:
        with pytest.raises(HTTPException) as error:
            await routes.verify_passenger_otp(body, request(), session)
        assert error.value.status_code == 401
        lookup.assert_not_awaited()
    issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_echoed_phone_cannot_swap_the_otp_proof_to_another_number():
    with pytest.raises(HTTPException):
        await challenge_phone(MagicMock(), hash_mobile_lookup(PHONE, purpose="passenger-phone"), "+919800000002")


@pytest.mark.asyncio
async def test_phone_removed_between_request_and_verify_cannot_issue_session(auth_environment, monkeypatch):
    session, _provider = auth_environment
    challenge_id = uuid.uuid4()
    challenge = SimpleNamespace(
        id=challenge_id, status="pending", expires_at=datetime.now(UTC) + timedelta(minutes=5),
        code_hash=hash_mobile_otp_code(challenge_id, "123456"), attempt_count=0, max_attempts=5,
        phone_lookup_hash=hash_mobile_lookup(PHONE, purpose="passenger-phone"),
    )
    monkeypatch.setattr(routes, "_locked_challenge", AsyncMock(return_value=challenge))
    monkeypatch.setattr(routes, "submitted_phone_rows", AsyncMock(return_value=[]))
    issue = AsyncMock()
    monkeypatch.setattr(routes, "_issue_passenger_session", issue)
    with pytest.raises(HTTPException) as error:
        await routes.verify_passenger_otp(MobileOTPVerifyRequest(
            challenge_id=challenge_id, code="123456", phone_number=PHONE,
            device=MobileDeviceInput(installation_id="synthetic-installation-123", platform="android", app_version="1.0.4"),
        ), request(), session)
    assert error.value.status_code == 401
    routes._reconcile_phone_candidate_groups.assert_awaited_once()
    issue.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_identity_with_changed_submitted_phone_is_not_eligible():
    passenger = submission(client_phone="+919800000002")
    legacy = SimpleNamespace(
        passenger_submission_id=passenger.id, group_id=passenger.group_id,
        agency_id=passenger.agency_id, normalized_phone_number=PHONE,
    )
    result = MagicMock()
    result.all.return_value = [(legacy, access(), SimpleNamespace(), passenger)]
    session = MagicMock(execute=AsyncMock(return_value=result))
    assert await routes._eligible_passenger_identities(session, "legacy-hash") == []


@pytest.mark.asyncio
async def test_sql_candidates_still_require_canonical_completed_collection_contact():
    good, imported, malformed = submission(), submission(confidence_score={"source": "excel_import"}), submission(client_phone="91letters9876543210")
    result = MagicMock()
    result.all.return_value = [(item, SimpleNamespace(), None) for item in (good, imported, malformed)]
    session = MagicMock(execute=AsyncMock(return_value=result))
    rows = await submitted_phone_rows(session, PHONE)
    assert [row[0] for row in rows] == [good]
    sql = str(session.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "whatsapp_broadcast" not in sql
    assert "client_groups.deleted_at IS NULL" in sql
    assert "'active', 'closed'" in sql
    assert "client_reviewed_at IS NOT NULL" in sql
    assert "passport_submissions.extracted_fields" not in sql
    assert "passport_submissions.confirmed_fields" not in sql
    assert "client_groups.name" not in sql
    assert "\\D" in sql and "'g'" in sql


@pytest.mark.asyncio
async def test_phone_discovery_overflow_never_authorizes_a_partial_shared_phone(monkeypatch):
    from app.presentation.api.v1.routes import mobile_auth_phone_support as support

    result = MagicMock()
    result.all.return_value = [(submission(), SimpleNamespace(), None)] * 101
    session = MagicMock(execute=AsyncMock(return_value=result))
    log = MagicMock()
    monkeypatch.setattr(support, "logger", log)
    assert await submitted_phone_rows(session, PHONE) == []
    log.warning.assert_called_once_with("mobile_otp_submitted_phone_lookup_overflow", candidate_limit=100)
    assert PHONE not in str(log.warning.call_args)


@pytest.mark.parametrize("status", ["trip_not_active", "trip_starts_later", "trip_access_ended"])
def test_guidance_response_contract_never_grants_tokens_or_claims(status):
    assert MobileOTPVerifyResponse(status=status).tokens is None


@pytest.mark.asyncio
async def test_refresh_rejects_stale_submitted_contact_before_issuing_offline_lease(monkeypatch):
    from app.presentation.api.v1.routes import mobile_auth_session_support as refresh

    session = MagicMock(execute=AsyncMock())
    guard = AsyncMock(return_value=False)
    monkeypatch.setattr(refresh, "ensure_current_passenger_session_bindings", guard)
    device_session = SimpleNamespace(subject_role="passenger")
    with pytest.raises(HTTPException) as error:
        await refresh._refresh_principal(session, device_session)
    assert error.value.status_code == 401
    guard.assert_awaited_once_with(session, device_session)
    session.execute.assert_not_awaited()
