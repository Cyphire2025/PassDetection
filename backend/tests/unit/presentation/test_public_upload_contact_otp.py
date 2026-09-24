"""Persisted OTP lifecycle and public final-submit bypass regressions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException, Request, Response
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.application.mobile.otp_provider import OTPDeliveryError
from app.domain.entities.entities import ClientGroup, PassportProcessingStatus, PassportSubmission
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel,
)
from app.infrastructure.security.mobile_otp_rate_limiter import (
    OTPRateLimitExceeded,
    OTPRateLimitUnavailable,
)
from app.presentation.api.v1.routes.passport_routes import contact_verification as routes
from app.presentation.api.v1.routes.passport_routes import (
    submission_contact,
    submission_review,
    submission_side_effects,
)
from app.presentation.api.v1.schemas.passport_schemas import ClientSubmitPassportRequest
from app.presentation.api.v1.schemas.public_upload_contact_schemas import (
    PublicContactOTPRequest,
    PublicContactOTPVerifyRequest,
)


@pytest.fixture
async def rig(db_session, monkeypatch):
    credential = "synthetic-private-upload-credential-" + "a" * 32
    group = ClientGroup.create("OTP group", "synthetic-public-link", uuid.uuid4(), uuid.uuid4())
    submission = PassportSubmission.create(group.id, group.agency_id, "Traveller", None, "front.jpg")
    submission.upload_idempotency_key = credential
    groups = SimpleNamespace(get_by_token=AsyncMock(return_value=group))
    passports = SimpleNamespace(get_by_id_for_update=AsyncMock(return_value=submission))
    monkeypatch.setattr(routes, "ClientGroupRepository", lambda _: groups)
    monkeypatch.setattr(routes, "PassportSubmissionRepository", lambda _: passports)
    settings = SimpleNamespace(
        app_secret_key="synthetic-contact-otp-secret",
        mobile=SimpleNamespace(
            otp_provider="development", otp_development_code=SecretStr("123456"),
            otp_max_attempts=3, otp_ttl_seconds=300, otp_resend_cooldown_seconds=30,
            otp_delivery_timeout_seconds=10,
        ),
    )
    monkeypatch.setattr(routes, "get_settings", lambda: settings)
    provider = SimpleNamespace(send_code=AsyncMock(return_value="fake-message-id"))
    monkeypatch.setattr(routes, "get_otp_provider", lambda: provider)
    limiter = SimpleNamespace(consume=AsyncMock())
    monkeypatch.setattr(routes, "PublicUploadOTPRateLimiter", lambda: limiter)
    request = Request({"type": "http", "headers": [], "client": ("192.0.2.10", 1234)})
    return SimpleNamespace(
        session=db_session, credential=credential, submission=submission, group=group,
        groups=groups, passports=passports, provider=provider, limiter=limiter,
        request=request, response=Response(), email="traveller@example.com", phone="+919876543210",
    )


async def send(rig, **changes):
    body = PublicContactOTPRequest(**{
        "group_token": rig.group.token, "email": rig.email, "phone_number": rig.phone, **changes,
    })
    return await routes.request_public_contact_otp(
        rig.submission.id, body, rig.request, rig.response,
        upload_session_id=rig.credential, session=rig.session,
    )


async def verify(rig, challenge_id, **changes):
    return await routes.verify_public_contact_otp(
        rig.submission.id,
        PublicContactOTPVerifyRequest(**{
            "group_token": rig.group.token, "challenge_id": challenge_id, "code": "123456", **changes,
        }),
        rig.response, upload_session_id=rig.credential, session=rig.session,
    )


async def proof(rig, challenge_id, **changes):
    return await routes.require_public_contact_proof(rig.session, **{
        "submission": rig.submission, "phone_verification_id": challenge_id,
        "upload_session_id": rig.credential, "client_phone": rig.phone, "client_email": rig.email,
        **changes,
    })


async def saved(rig):
    return (await rig.session.execute(select(PublicUploadContactChallengeModel))).scalar_one()


async def test_request_persists_sending_state_before_provider_and_stores_only_hash(rig):
    async def deliver(**kwargs):
        row = await saved(rig)
        assert row.status == "sending"
        assert row.code_hash != kwargs["code"]
        assert row.upload_session_hash != rig.credential
        assert row.email_hash != rig.email
        # A provider callback cannot verify a code before outcome persistence.
        with pytest.raises(HTTPException):
            await verify(rig, row.id)
        return "fake-message-id"
    rig.provider.send_code.side_effect = deliver
    response = await send(rig)
    row = await saved(rig)
    assert row.status == "pending"
    assert row.id == response.challenge_id
    assert response.resend_after_seconds == 30
    assert 298 <= response.expires_in_seconds <= 300
    assert "no-store" in rig.response.headers["cache-control"]
    rig.passports.get_by_id_for_update.assert_awaited()


async def test_valid_code_unlocks_bound_proof_and_verify_retry_does_not_extend_expiry(rig):
    challenge = await send(rig)
    verified = await verify(rig, challenge.challenge_id)
    assert verified.phone_number == rig.phone
    assert verified.expires_in_seconds == 3600
    row = await proof(rig, verified.phone_verification_id, client_phone="98765 43210")
    expires = row.proof_expires_at
    assert row.code_hash is None
    repeated = await verify(rig, challenge.challenge_id)
    assert repeated.phone_verification_id == verified.phone_verification_id
    assert (await saved(rig)).proof_expires_at == expires


@pytest.mark.parametrize("status", ["sending", "pending", "failed", "locked"])
async def test_unverified_challenge_cannot_authorize_submission(rig, status):
    challenge = await send(rig)
    row = await saved(rig)
    row.status = status
    await rig.session.commit()
    with pytest.raises(HTTPException) as error:
        await proof(rig, challenge.challenge_id)
    assert error.value.detail["code"] == "CONTACT_VERIFICATION_REQUIRED"


async def test_wrong_code_attempts_are_committed_and_exhaustion_blocks_correct_code(rig):
    challenge = await send(rig)
    for attempt in range(1, 4):
        with pytest.raises(HTTPException):
            await verify(rig, challenge.challenge_id, code="654321")
        await rig.session.rollback()
        row = await saved(rig)
        assert row.attempt_count == attempt
    assert row.status == "locked"
    assert row.code_hash is None
    with pytest.raises(HTTPException):
        await verify(rig, challenge.challenge_id)


async def test_expired_code_rejected(rig):
    challenge = await send(rig)
    (await saved(rig)).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await rig.session.commit()
    with pytest.raises(HTTPException):
        await verify(rig, challenge.challenge_id)


async def test_resend_during_cooldown_reuses_challenge_without_sending(rig):
    first = await send(rig)
    second = await send(rig)
    assert second.challenge_id == first.challenge_id
    rig.provider.send_code.assert_awaited_once()
    with pytest.raises(HTTPException) as error:
        await send(rig, phone_number="+919876543211")
    assert error.value.status_code == 429
    assert int(error.value.headers["Retry-After"]) > 0


async def test_resend_rotates_id_and_invalidates_old_verified_proof(rig):
    first = await send(rig)
    await verify(rig, first.challenge_id)
    (await saved(rig)).resend_available_at = datetime.now(UTC) - timedelta(seconds=1)
    await rig.session.commit()
    second = await send(rig)
    assert second.challenge_id != first.challenge_id
    with pytest.raises(HTTPException):
        await verify(rig, first.challenge_id)
    with pytest.raises(HTTPException):
        await proof(rig, first.challenge_id)
    await verify(rig, second.challenge_id)


@pytest.mark.parametrize("error", [OTPDeliveryError("Failed"), OTPDeliveryError("Unknown", delivery_unknown=True), RuntimeError("Unexpected")])
async def test_provider_failure_is_durable_and_fails_closed(rig, error):
    rig.provider.send_code.side_effect = error
    with pytest.raises(HTTPException) as failure:
        await send(rig)
    assert failure.value.status_code == 503
    row = await saved(rig)
    assert row.status == "failed"
    assert row.code_hash is None
    with pytest.raises(HTTPException):
        await verify(rig, row.id)


@pytest.mark.parametrize("error,status", [(OTPRateLimitExceeded(), 429), (OTPRateLimitUnavailable(), 503)])
async def test_abuse_limit_blocks_send(rig, error, status):
    rig.limiter.consume.side_effect = error
    with pytest.raises(HTTPException) as failure:
        await send(rig)
    assert failure.value.status_code == status
    rig.provider.send_code.assert_not_awaited()


@pytest.mark.parametrize("change", ["phone", "email", "session", "group", "submission", "id", "expiry"])
async def test_verified_proof_cannot_change_scope(rig, change):
    challenge = await send(rig)
    await verify(rig, challenge.challenge_id)
    changes = {}
    if change == "phone":
        changes["client_phone"] = "+919876543211"
    elif change == "email":
        changes["client_email"] = "someoneelse@example.com"
    elif change == "session":
        changes["upload_session_id"] = "b" * 48
    elif change == "group":
        rig.submission.group_id = uuid.uuid4()
    elif change == "submission":
        rig.submission.id = uuid.uuid4()
    elif change == "id":
        challenge.challenge_id = uuid.uuid4()  # Includes mobile-login challenge ids.
    else:
        (await saved(rig)).proof_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await rig.session.commit()
    with pytest.raises(HTTPException) as error:
        await proof(rig, challenge.challenge_id, **changes)
    assert error.value.status_code == 400


@pytest.mark.parametrize("change", ["credential", "group", "inactive", "import_only", "submitted"])
async def test_request_requires_active_unsubmitted_upload_capability(rig, change):
    if change == "credential":
        rig.credential = "b" * 48
    elif change == "group":
        rig.submission.group_id = uuid.uuid4()
    elif change == "inactive":
        rig.groups.get_by_token.return_value = None
    elif change == "import_only":
        rig.group.import_only = True
    else:
        rig.submission.status = PassportProcessingStatus.SUBMITTED
    with pytest.raises(HTTPException):
        await send(rig)
    rig.provider.send_code.assert_not_awaited()


async def test_consumed_proof_allows_exact_submit_retry_after_expiry_only(rig):
    challenge = await send(rig)
    await verify(rig, challenge.challenge_id)
    row = await saved(rig)
    row.status = "consumed"
    row.consumed_at = datetime.now(UTC)
    row.proof_expires_at = datetime.now(UTC) - timedelta(hours=1)
    await rig.session.commit()
    with pytest.raises(HTTPException):
        await proof(rig, challenge.challenge_id)
    rig.submission.status = PassportProcessingStatus.SUBMITTED
    rig.submission.client_email = rig.email
    rig.submission.client_phone = rig.phone
    assert await proof(rig, challenge.challenge_id) is row
    with pytest.raises(HTTPException):
        await verify(rig, challenge.challenge_id)
    with pytest.raises(HTTPException):
        await proof(rig, challenge.challenge_id, client_phone="+919876543211")


async def test_final_submit_rejects_bypass_before_usecase_or_storage(rig, monkeypatch):
    monkeypatch.setattr(submission_contact, "PassportSubmissionRepository", lambda _: rig.passports)
    use_case = SimpleNamespace(execute=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await submission_review.client_submit_passport(
            rig.submission.id,
            ClientSubmitPassportRequest(
                group_token=rig.group.token, confirmed_fields={"given_names": "Traveller"},
                client_email=rig.email, client_phone=rig.phone, phone_verification_id=uuid.uuid4(),
            ),
            BackgroundTasks(), upload_session_id=rig.credential, use_case=use_case, session=rig.session,
        )
    assert error.value.detail["field"] == "phone_verification_id"
    use_case.execute.assert_not_awaited()


@pytest.mark.parametrize("tampered", ["family_head_email", "family_head_phone"])
async def test_final_submit_invokes_family_head_gate_before_usecase(rig, monkeypatch, tampered):
    challenge = await send(rig)
    await verify(rig, challenge.challenge_id)
    monkeypatch.setattr(submission_contact, "PassportSubmissionRepository", lambda _: rig.passports)
    use_case = SimpleNamespace(execute=AsyncMock())
    fields = dict(
        group_token=rig.group.token, confirmed_fields={"given_names": "Traveller"},
        client_email=rig.email, client_phone=rig.phone, phone_verification_id=challenge.challenge_id,
        submission_mode="family", family_group_id=uuid.uuid4(), family_member_index=0,
        family_head_name="Family Head", family_head_email=rig.email, family_head_phone=rig.phone,
    )
    fields[tampered] = "someoneelse@example.com" if tampered == "family_head_email" else "+919876543211"
    with pytest.raises(HTTPException) as error:
        await submission_review.client_submit_passport(
            rig.submission.id, ClientSubmitPassportRequest(**fields), BackgroundTasks(),
            upload_session_id=rig.credential, use_case=use_case, session=rig.session,
        )
    assert error.value.detail["code"] == "FAMILY_CONTACT_VERIFICATION_REQUIRED"
    use_case.execute.assert_not_awaited()
    assert (await saved(rig)).status == "verified"


@pytest.mark.parametrize("commit_fails", [False, True])
async def test_final_submit_consumes_proof_atomically_and_failed_commit_preserves_it(rig, monkeypatch, commit_fails):
    challenge = await send(rig)
    await verify(rig, challenge.challenge_id)
    monkeypatch.setattr(submission_contact, "PassportSubmissionRepository", lambda _: rig.passports)
    monkeypatch.setattr(submission_side_effects, "propagate_mobile_passenger_change", AsyncMock())
    monkeypatch.setattr(submission_side_effects, "AuditLogRepository", lambda _: SimpleNamespace(record=AsyncMock()))
    monkeypatch.setattr(submission_side_effects, "NotificationRepository", lambda _: SimpleNamespace(create=AsyncMock()))
    monkeypatch.setattr(submission_review.PassportSubmissionResponse, "model_validate", lambda value: value)
    result = SimpleNamespace(
        id=rig.submission.id, agency_id=rig.group.agency_id, group_id=rig.group.id,
        image_s3_key="", idempotent_replay=False, storage_cleanup_keys=(), promoted_storage_keys=(),
        submission_mode="single", qualifier_enabled_snapshot=False,
    )
    use_case = SimpleNamespace(execute=AsyncMock(return_value=result))
    if commit_fails:
        monkeypatch.setattr(rig.session, "commit", AsyncMock(side_effect=RuntimeError("injected commit failure")))
    args = dict(
        submission_id=rig.submission.id,
        body=ClientSubmitPassportRequest(
            group_token=rig.group.token, confirmed_fields={"given_names": "Traveller"},
            client_email=rig.email, client_phone=rig.phone, phone_verification_id=challenge.challenge_id,
        ),
        background_tasks=BackgroundTasks(), upload_session_id=rig.credential,
        use_case=use_case, session=rig.session,
    )
    if commit_fails:
        with pytest.raises(RuntimeError, match="injected commit failure"):
            await submission_review.client_submit_passport(**args)
        # Mirror the request-scoped transaction dependency's rollback.
        await rig.session.rollback()
        assert (await saved(rig)).status == "verified"
        assert (await saved(rig)).consumed_at is None
    else:
        assert await submission_review.client_submit_passport(**args) is result
        assert (await saved(rig)).status == "consumed"
        assert (await saved(rig)).consumed_at is not None


@pytest.mark.parametrize("field", ["client_email", "client_phone", "phone_verification_id"])
def test_final_schema_requires_contact_and_proof(field):
    body = dict(group_token="synthetic-public-link", confirmed_fields={"given_names": "Traveller"},
                client_email="traveller@example.com", client_phone="9876543210", phone_verification_id=uuid.uuid4())
    del body[field]
    with pytest.raises(ValidationError):
        ClientSubmitPassportRequest(**body)


@pytest.mark.parametrize("phone", ["+9198765432", "+91987654321", "+9198765432101", "98765432101", "987654321", "not-a-number"])
def test_request_rejects_incomplete_or_ambiguous_phone(phone):
    with pytest.raises(ValidationError):
        PublicContactOTPRequest(group_token="synthetic-public-link", email="traveller@example.com", phone_number=phone)


async def test_challenge_select_locks_and_refreshes_existing_rows():
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)
    await routes._locked_challenge(session, uuid.uuid4())
    statement = session.execute.await_args.args[0]
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
    assert statement.get_execution_options()["populate_existing"]


@pytest.mark.parametrize("change", [None, "phone", "email", "index"])
async def test_first_family_member_head_contact_must_match_own_verified_contact(rig, change):
    challenge = await send(rig)
    await verify(rig, challenge.challenge_id)
    own_proof = await saved(rig)
    kwargs = dict(
        submission=rig.submission, own_proof=own_proof,
        family_group_id=uuid.uuid4(), family_member_index=0,
        family_head_email=rig.email, family_head_phone=rig.phone,
    )
    if change == "phone":
        kwargs["family_head_phone"] = "+919876543211"
    elif change == "email":
        kwargs["family_head_email"] = "another@example.com"
    elif change == "index":
        kwargs["family_member_index"] = None
    if change is None:
        await routes.require_verified_family_head(rig.session, **kwargs)
    else:
        with pytest.raises(HTTPException) as error:
            await routes.require_verified_family_head(rig.session, **kwargs)
        assert error.value.detail["code"] == "FAMILY_CONTACT_VERIFICATION_REQUIRED"


@pytest.mark.parametrize("change", [None, "retry", "phone", "email", "legacy", "not_submitted", "wrong_family", "wrong_group", "changed_head"])
async def test_later_family_members_use_persisted_consumed_head_proof(rig, change):
    challenge = await send(rig)
    await verify(rig, challenge.challenge_id)
    head_proof = await saved(rig)
    head_proof.status = "consumed" if change != "legacy" else "verified"
    head_proof.consumed_at = datetime.now(UTC) if change != "legacy" else None
    # Completed head receipts remain valid across a partial family retry.
    head_proof.proof_expires_at = datetime.now(UTC) - timedelta(hours=1)
    family_id = uuid.uuid4()
    head = PassportSubmissionModel(
        id=rig.submission.id, group_id=rig.group.id, agency_id=rig.group.agency_id,
        image_s3_key="head.jpg", client_name="Family Head", client_email=rig.email,
        client_phone=rig.phone, submission_mode="family", family_member_index=0,
        family_group_id=family_id, status="needs_review",
    )
    if change == "not_submitted":
        head.status = "processing"
    elif change == "wrong_family":
        head.family_group_id = uuid.uuid4()
    elif change == "wrong_group":
        head.group_id = uuid.uuid4()
    elif change == "changed_head":
        head.client_phone = "+919876543211"
    rig.session.add(head)
    await rig.session.commit()
    member = PassportSubmission.create(rig.group.id, rig.group.agency_id, "Second Member", None, "member.jpg")
    if change == "retry":
        member.status = PassportProcessingStatus.SUBMITTED
    kwargs = dict(
        submission=member, own_proof=head_proof, family_group_id=family_id, family_member_index=1,
        family_head_email="other@example.com" if change == "email" else rig.email,
        family_head_phone="+919876543211" if change == "phone" else rig.phone,
    )
    if change in {None, "retry"}:
        await routes.require_verified_family_head(rig.session, **kwargs)
    else:
        with pytest.raises(HTTPException) as error:
            await routes.require_verified_family_head(rig.session, **kwargs)
        assert error.value.detail["code"] == "FAMILY_CONTACT_VERIFICATION_REQUIRED"
