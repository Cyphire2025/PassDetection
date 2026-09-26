"""Internal half of the fixed synthetic two-API restart qualification."""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from app.core.security.identity_security import encrypt_mfa_secret
from app.core.security.password import hash_password
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.session import AsyncSessionFactory, engine
from qualification_application_journey import isolated
from upload_configuration_http_smoke import REQUIRED_FIELD_NAMES, synthetic_cover, totp

PEER = "http://passdetection-qualification-api-peer:8000"
ORIGIN = "https://localhost:58443"


async def call(client, method, path, expected=200, **kwargs):
    result = await client.request(method, path, **kwargs)
    assert result.status_code == expected, f"{method} {path}: expected {expected}, got {result.status_code}"
    return result


async def first(*, verify_peer: bool = True) -> dict:
    token = uuid.uuid4().hex
    agency, user = uuid.uuid4(), uuid.uuid4()
    email, password, secret = f"replica-{token}@example.test", "Synthetic-Replica-937!", "JBSWY3DPEHPK3PXP"
    async with AsyncSessionFactory() as db:
        db.add(AgencyModel(id=agency, name="Synthetic replica qualification", email=email))
        await db.flush()
        db.add(UserModel(id=user, agency_id=agency, email=email, full_name="Synthetic replica manager",
                         role="agency_manager", hashed_password=hash_password(password), is_active=True))
        await db.flush()
        now = datetime.now(UTC)
        db.add(UserSecurityStateModel(user_id=user, credential_state="active", session_version=1,
                                      password_changed_at=now, mfa_required=True,
                                      mfa_secret_ciphertext=encrypt_mfa_secret(secret), mfa_enabled_at=now))
        await db.commit()
    async with httpx.AsyncClient(base_url="http://backend:8000", timeout=60, headers={"Origin": ORIGIN}) as client:
        challenge = (await call(client, "POST", "/api/v1/auth/login", data={"username": email, "password": password})).json()
        result = await call(client, "POST", "/api/v1/auth/mfa/verify",
                            json={"challenge_token": challenge["challenge_token"], "code": totp(secret)})
        cookies = "; ".join(f"{key}={value}" for key, value in result.cookies.items())
        assert "access_token=" in cookies and "refresh_token=" in cookies
        # Direct internal HTTP targets are intentional: manually transport the
        # already issued cookies to select each instance. Browser/TLS semantics
        # are qualified separately by the real three-engine browser lane.
        client.headers["Cookie"] = cookies
        date = datetime.now(UTC).date() + timedelta(days=30)
        group = (await call(client, "POST", "/api/v1/upload-links", expected=201, json={
            "name": f"Synthetic Replica {token}", "destination": "Synthetic destination",
            "travel_date": date.isoformat(), "return_date": (date + timedelta(days=3)).isoformat(),
            "upload_configuration": {"passport_upload_pages": ["cover", "back_cover"], "passport_live_scan": False,
                                     "required_fields": {key: False for key in REQUIRED_FIELD_NAMES}},
        })).json()
        capability = secrets.token_urlsafe(40)
        submission = (await call(client, "POST", f"/api/v1/passports/upload/{group['token']}", expected=201,
            headers={"X-Upload-Session-ID": capability}, data={"client_name": "Synthetic Replica Traveller",
            "acquisition_mode": "file", "upload_idempotency_key": capability}, files={
                "passport_cover_file": ("cover.jpg", synthetic_cover("REPLICA COVER"), "image/jpeg"),
                "passport_back_cover_file": ("back.jpg", synthetic_cover("REPLICA BACK"), "image/jpeg"),
            })).json()
        route = f"/api/v1/passports/upload/{group['token']}/{submission['id']}/image/cover"
        image = await call(client, "GET", route, headers={"X-Upload-Session-ID": capability})
    proof = {"user_id": str(user), "cookies": cookies, "route": route, "capability": capability,
             "checksum": hashlib.sha256(image.content).hexdigest(), "submission_id": submission["id"]}
    if verify_peer:
        await verify(PEER, proof)
    return proof


async def verify(base_url: str, proof: dict, *, revoke: bool = False, revoked: bool = False) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=60, headers={"Origin": ORIGIN, "Cookie": proof["cookies"]}) as client:
        response = await call(client, "GET", "/api/v1/auth/me", expected=401 if revoked else 200)
        if revoked:
            return
        assert response.json()["id"] == proof["user_id"]
        image = await call(client, "GET", proof["route"], headers={"X-Upload-Session-ID": proof["capability"]})
        assert hashlib.sha256(image.content).hexdigest() == proof["checksum"]
        if revoke:
            await call(client, "POST", "/api/v1/auth/logout", expected=204, json={})


async def main() -> None:
    isolated()
    try:
        if sys.argv[1] == "first":
            print(json.dumps(await first()))
        elif sys.argv[1] == "dependency-before":
            proof = await first(verify_peer=False)
            async with httpx.AsyncClient(base_url="http://backend:8000", timeout=30) as client:
                baseline = await client.get("/api/v1/health/ready")
                assert baseline.status_code in (200, 503)
                assert baseline.json()["checks"]["database"] == "ok"
                proof["readiness_baseline"] = {"http_status": baseline.status_code, "body": baseline.json()}
            print(json.dumps(proof))
        elif sys.argv[1] == "dependency-down":
            proof = json.load(sys.stdin)
            async with httpx.AsyncClient(base_url="http://backend:8000", timeout=30,
                    headers={"Origin": ORIGIN, "Cookie": proof["cookies"]}) as client:
                await call(client, "GET", "/api/v1/health/live")
                ready = await call(client, "GET", "/api/v1/health/ready", expected=503)
                database_status = ready.json()["checks"]["database"]
                assert database_status in {"unreachable", "probe_timeout", "probe_failed"}, database_status
                for route, headers in (("/api/v1/auth/me", {}),
                                       (proof["route"], {"X-Upload-Session-ID": proof["capability"]})):
                    result = await client.get(route, headers=headers)
                    assert result.status_code in (500, 503), "Dependency loss must not authorize a private response"
                    assert result.headers["content-type"].startswith("application/json")
                    body = result.json()
                    assert body["error"]["code"] in ("INTERNAL_SERVER_ERROR", "DEPENDENCY_UNAVAILABLE")
                    assert proof["user_id"] not in result.text and proof["submission_id"] not in result.text
            print(json.dumps({"liveness_200_database_unavailable_readiness_503": True,
                              "database_unavailable_probe_status": database_status,
                              "authenticated_and_private_reads_fail_closed": True}))
        elif sys.argv[1] == "dependency-restored":
            proof = json.load(sys.stdin)
            await verify("http://backend:8000", proof)
            async with httpx.AsyncClient(base_url="http://backend:8000", timeout=30) as client:
                baseline = proof["readiness_baseline"]
                result = await call(client, "GET", "/api/v1/health/ready", expected=baseline["http_status"])
                restored = result.json()
                assert restored["checks"]["database"] == "ok"
                assert restored["checks"]["database_schema"] == "compatible"
                for name, capability in baseline["body"]["capabilities"].items():
                    if capability.get("available"):
                        assert restored["capabilities"][name]["available"], f"Previously healthy capability {name} did not recover"
            print(json.dumps({"same_session_private_object_checksum_and_readiness_baseline_restored": True,
                              "overall_readiness_status_before_and_after": baseline["http_status"],
                              "preexisting_unavailable_capabilities": [name for name, capability in baseline["body"]["capabilities"].items()
                                                                       if not capability.get("available")]}))
        elif sys.argv[1] == "survivor":
            await verify(PEER, json.load(sys.stdin), revoke=True)
            print(json.dumps({"shared_session_and_accepted_upload_survived_origin_stop": True, "logout_on_peer": True}))
        elif sys.argv[1] == "restarted":
            await verify("http://backend:8000", json.load(sys.stdin), revoked=True)
            print(json.dumps({"restarted_origin_rejects_peer_revoked_cookie": True}))
        else:
            raise RuntimeError("Unknown qualification phase")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
