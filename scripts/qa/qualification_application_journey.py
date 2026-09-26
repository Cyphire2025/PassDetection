"""Real HTTPS/API/PostgreSQL/private-storage journey using synthetic data only.

The WhatsApp delivery provider is deliberately excluded. A pending challenge is
seeded directly, then the real OTP verification and submission endpoints run.
No API routes, storage adapters, scanner calls, or persistence calls are mocked.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from app.core.config.settings import get_settings
from app.core.security.identity_security import encrypt_mfa_secret
from app.core.security.password import hash_password
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel,
)
from app.infrastructure.database.session import AsyncSessionFactory, engine
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.passport_routes.contact_verification import (
    _code_digest,
    _digest,
)
from PIL import Image
from seed_enterprise_browser_stack import AGENCY_ID, MANAGER_PASSWORD, MANAGERS
from sqlalchemy import func, select
from upload_configuration_http_smoke import REQUIRED_FIELD_NAMES, synthetic_cover, totp


def isolated() -> None:
    if (os.environ.get("POSTGRES_DB") != "passdetection_ci_browser"
            or os.environ.get("S3_ENDPOINT_URL") != "http://minio:9000"
            or not get_settings().is_production):
        raise RuntimeError("Only the disposable production-mode qualification stack is accepted")


async def request(client: httpx.AsyncClient, method: str, path: str, *, expected: int = 200, **kwargs):
    response = await client.request(method, path, **kwargs)
    if response.status_code != expected:
        raise AssertionError(f"{method} {path.split('?')[0]}: expected {expected}, got {response.status_code}: {response.text[:300]}")
    return response


async def assert_other_tenant_denied(submission_id: str, run_id: str) -> None:
    agency_id, user_id = uuid.uuid4(), uuid.uuid4()
    email, secret = f"qualification-other-{run_id}@example.test", "JBSWY3DPEHPK3PXP"
    now = datetime.now(UTC)
    async with AsyncSessionFactory() as db:
        db.add(AgencyModel(id=agency_id, name="Synthetic Other Tenant", email=email))
        await db.flush()
        db.add(UserModel(id=user_id, agency_id=agency_id, email=email,
                         full_name="Synthetic Other Tenant Manager", role="agency_manager",
                         hashed_password=hash_password(MANAGER_PASSWORD), is_active=True))
        await db.flush()
        db.add(UserSecurityStateModel(user_id=user_id, credential_state="active", session_version=1,
                                      password_changed_at=now, mfa_required=True,
                                      mfa_secret_ciphertext=encrypt_mfa_secret(secret), mfa_enabled_at=now))
        await db.commit()
    async with httpx.AsyncClient(base_url="https://nginx", verify=False, timeout=60,
                                 headers={"Origin": "https://localhost:58443"}) as other:
        challenge = (await request(other, "POST", "/api/v1/auth/login", data={
            "username": email, "password": MANAGER_PASSWORD,
        })).json()
        await request(other, "POST", "/api/v1/auth/mfa/verify", json={
            "challenge_token": challenge["challenge_token"], "code": totp(secret),
        })
        await request(other, "GET", f"/api/v1/passports/{submission_id}/covers/cover", expected=403)
        await request(other, "POST", "/api/v1/auth/logout", expected=204, json={})


async def main() -> None:
    isolated()
    run_id = uuid.uuid4().hex
    checks: list[str] = []
    # This fixed internal address resolves only inside the disposable project.
    # The production Nginx configuration terminates its generated localhost cert.
    async with httpx.AsyncClient(base_url="https://nginx", verify=False, timeout=60,
                                 headers={"Origin": "https://localhost:58443"}) as staff, \
            httpx.AsyncClient(base_url="https://nginx", verify=False, timeout=60) as public:
        live = (await request(public, "GET", "/api/v1/health/live")).json()
        assert live["environment"] == "production"
        _, email, mfa_secret = MANAGERS["mobile"]  # separate synthetic account from browser tests
        auth = (await request(staff, "POST", "/api/v1/auth/login", data={
            "username": email, "password": MANAGER_PASSWORD,
        })).json()
        auth = (await request(staff, "POST", "/api/v1/auth/mfa/verify", json={
            "challenge_token": auth["challenge_token"], "code": totp(mfa_secret),
        })).json()
        assert auth["user"]["agency_id"] == str(AGENCY_ID)
        checks.append("production_tls_password_and_mfa_authentication")
        travel_date = datetime.now(UTC).date() + timedelta(days=30)
        group = (await request(staff, "POST", "/api/v1/upload-links", expected=201, json={
            "name": f"Qualification Synthetic {run_id}", "destination": "Synthetic destination",
            "travel_date": travel_date.isoformat(), "return_date": (travel_date + timedelta(days=3)).isoformat(),
            "upload_configuration": {"passport_upload_pages": ["cover", "back_cover"],
                                     "passport_live_scan": False,
                                     "required_fields": {name: False for name in REQUIRED_FIELD_NAMES}},
        })).json()
        capability = secrets.token_urlsafe(40)
        headers = {"X-Upload-Session-ID": capability}
        submission = (await request(public, "POST", f"/api/v1/passports/upload/{group['token']}", expected=201,
            headers=headers, data={"client_name": "Synthetic Qualification Traveller", "acquisition_mode": "file",
                                  "upload_idempotency_key": capability},
            files={"passport_cover_file": ("cover.jpg", synthetic_cover("QUALIFICATION COVER"), "image/jpeg"),
                   "passport_back_cover_file": ("back-cover.jpg", synthetic_cover("QUALIFICATION BACK"), "image/jpeg")},
        )).json()
        assert submission["processing_job_id"] is None
        assert submission["passport_cover_s3_key"]
        checks.append("real_clamav_scanned_cover_upload_and_postgresql_persistence")
        public_preview = f"/api/v1/passports/upload/{group['token']}/{submission['id']}/image/cover"
        preview = await request(public, "GET", public_preview, headers=headers)
        with Image.open(io.BytesIO(preview.content)) as image:
            assert image.size == (540, 760)
        await request(public, "GET", public_preview, expected=404,
                      headers={"X-Upload-Session-ID": secrets.token_urlsafe(40)})
        await request(public, "GET", f"/api/v1/passports/{submission['id']}/covers/cover", expected=401)
        checks.append("private_document_rejects_anonymous_and_wrong_upload_capability")
        contact_email, phone, code = f"qualification-{run_id}@example.com", "+12025550137", "638291"
        challenge_id = uuid.uuid4()
        now = datetime.now(UTC)
        async with AsyncSessionFactory() as db:
            row = await db.get(PassportSubmissionModel, uuid.UUID(submission["id"]))
            owner = await db.get(ClientGroupModel, row.group_id)
            assert row.agency_id == AGENCY_ID and owner.name == f"Qualification Synthetic {run_id}"
            db.add(PublicUploadContactChallengeModel(
                submission_id=row.id, id=challenge_id, group_id=row.group_id,
                upload_session_hash=_digest("upload-session", capability), email_hash=_digest("email", contact_email),
                phone_number=phone, code_hash=_code_digest(challenge_id, code), status="pending",
                attempt_count=0, max_attempts=5, expires_at=now + timedelta(minutes=5),
                resend_available_at=now, created_at=now, updated_at=now,
            ))
            await db.commit()
        proof = (await request(public, "POST", f"/api/v1/passports/{submission['id']}/contact-otp/verify",
            headers=headers, json={"group_token": group["token"], "challenge_id": str(challenge_id), "code": code},
        )).json()
        final = (await request(public, "POST", f"/api/v1/passports/{submission['id']}/client-submit", headers=headers,
            json={"group_token": group["token"], "confirmed_fields": {"given_names": "Synthetic Qualification Traveller"},
                  "client_email": contact_email, "client_phone": phone,
                  "phone_verification_id": proof["phone_verification_id"]},
        )).json()
        assert final["status"] == "needs_review"
        assert not final["passport_cover_s3_key"].startswith("drafts/")
        assert final["post_submission_verified_at"] is None
        checks.append("real_contact_proof_consumption_and_final_document_promotion")
        staff_preview = await request(staff, "GET", f"/api/v1/passports/{submission['id']}/covers/cover")
        assert staff_preview.headers["cache-control"].startswith("private")
        checksum = hashlib.sha256(staff_preview.content).hexdigest()
        storage = MinioStorageRepository()
        assert hashlib.sha256(await storage.get_file(final["passport_cover_s3_key"])).hexdigest() == checksum
        async with AsyncSessionFactory() as db:
            persisted = await db.get(PassportSubmissionModel, uuid.UUID(submission["id"]))
            consumed = await db.get(PublicUploadContactChallengeModel, persisted.id)
            assert persisted.status == "needs_review" and consumed.status == "consumed"
            assert persisted.client_reviewed_at is not None
            audit_count = await db.scalar(select(func.count()).select_from(AuditLogModel)
                                         .where(AuditLogModel.entity_id == str(persisted.id)))
            assert audit_count > 0
        anonymous_object = await public.get(f"http://minio:9000/passdetection-passports/{final['passport_cover_s3_key']}")
        assert anonymous_object.status_code == 403
        checks.append("authenticated_private_object_checksum_and_durable_audit_trail")
        await assert_other_tenant_denied(submission["id"], run_id)
        checks.append("authenticated_other_tenant_manager_cannot_read_private_document")
        await request(staff, "POST", "/api/v1/auth/logout", expected=204, json={})
        print(json.dumps({"synthetic": True, "checks": checks, "submission_id": submission["id"],
                          "object_key": final["passport_cover_s3_key"], "object_sha256": checksum,
                          "external_otp_delivery_tested": False, "external_ai_invoked": False}))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
