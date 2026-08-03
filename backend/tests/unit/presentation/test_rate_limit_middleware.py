from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from starlette.requests import Request
from starlette.responses import Response

from app.core.config.settings import Settings
from app.core.security.upload_session import upload_session_matches_identifier
from app.domain.exceptions.exceptions import AuthenticationError
from app.main import create_application
from app.presentation.middleware.rate_limit import RateLimitMiddleware


class _FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.counts: dict[str, int] = {}
        self.expirations: dict[str, int] = {}
        self.token_buckets: dict[str, int] = {}
        self.fail = fail

    async def incr(self, key: str) -> int:
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.expirations[key] = ttl

    async def eval(
        self,
        _script: str,
        _numkeys: int,
        key: str,
        _refill_per_second: int,
        capacity: int,
        ttl_ms: int,
    ) -> list[int]:
        if self.fail:
            raise ConnectionError("redis unavailable")
        remaining = self.token_buckets.get(key, int(capacity))
        if remaining <= 0:
            return [0, 0, 1000]
        remaining -= 1
        self.token_buckets[key] = remaining
        self.expirations[key] = int(ttl_ms)
        return [1, remaining, 0]


async def _ok(_: Request) -> Response:
    return Response("ok")


def _request(
    *,
    path: str,
    method: str = "POST",
    session_id: str | None = None,
    real_ip: str = "203.0.113.10",
    forwarded_for: str | None = None,
    origin: str | None = None,
    access_token: str | None = None,
    use_cookie: bool = False,
) -> Request:
    headers: list[tuple[bytes, bytes]] = [(b"x-real-ip", real_ip.encode("ascii"))]
    if session_id is not None:
        headers.append((b"x-upload-session-id", session_id.encode("ascii")))
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("ascii")))
    if origin is not None:
        headers.append((b"origin", origin.encode("ascii")))
    if access_token is not None:
        if use_cookie:
            headers.append((b"cookie", f"access_token={access_token}".encode("ascii")))
        else:
            headers.append((b"authorization", f"Bearer {access_token}".encode("ascii")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": headers,
            "client": ("198.51.100.77", 54321),
            "server": ("testserver", 443),
        }
    )


class PublicUploadRateLimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        RateLimitMiddleware._local_counts.clear()
        RateLimitMiddleware._local_token_buckets.clear()
        self.redis = _FakeRedis()
        self.settings = SimpleNamespace(
            app_secret_key="test-only-secret-with-sufficient-entropy",
            allowed_origins=["https://tech.gctravels.com"],
            rate_limit_per_minute=60,
            dashboard_rate_limit_per_minute=5_000,
            dashboard_rate_limit_per_second=50,
            dashboard_rate_limit_burst=150,
            dashboard_media_rate_limit_per_minute=30_000,
            dashboard_media_rate_limit_per_second=30,
            dashboard_media_rate_limit_burst=60,
            dashboard_rate_limit_require_redis=True,
            jwt=SimpleNamespace(access_cookie_name="access_token"),
            public_upload_bootstrap_session_rate_limit_per_minute=30,
            public_upload_bootstrap_aggregate_rate_limit_per_minute=600,
            public_upload_session_rate_limit_per_minute=6,
            public_upload_aggregate_rate_limit_per_minute=180,
            public_upload_followup_session_rate_limit_per_minute=120,
            public_upload_followup_aggregate_rate_limit_per_minute=6_000,
            public_upload_rate_limit_require_redis=True,
        )
        self.middleware = RateLimitMiddleware(
            _ok,
            settings=self.settings,
            redis_client=self.redis,
            initialize_redis=False,
        )

    def test_application_factory_injects_its_settings_into_rate_limiter(
        self,
    ) -> None:
        settings = Settings(
            app_env="development",
            app_secret_key="factory-test-secret-not-for-production",
            public_upload_rate_limit_require_redis=False,
            _env_file=None,
        )

        app = create_application(settings=settings)
        registration = next(
            middleware
            for middleware in app.user_middleware
            if middleware.cls is RateLimitMiddleware
        )

        self.assertIs(registration.kwargs["settings"], settings)

    def test_upload_header_is_bound_exactly_to_idempotency_key(self) -> None:
        attempt_id = "attempt-12345678-abcdef-1234567890"
        self.assertTrue(upload_session_matches_identifier(attempt_id, attempt_id))
        self.assertFalse(
            upload_session_matches_identifier(
                attempt_id,
                "attempt-87654321-abcdef-1234567890",
            )
        )
        self.assertFalse(
            upload_session_matches_identifier(
                f" {attempt_id}",
                f" {attempt_id}",
            )
        )

    async def test_options_preflight_never_requires_or_consumes_a_session(self) -> None:
        response = await self.middleware.dispatch(
            _request(
                path="/api/v1/passports/submission-12345678/client-submit",
                method="OPTIONS",
            ),
            _ok,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.redis.counts, {})

    async def test_one_hundred_client_submits_share_followup_budget(self) -> None:
        path = "/api/v1/passports/submission-12345678/client-submit"
        missing = await self.middleware.dispatch(
            _request(path=path),
            _ok,
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(
            json.loads(missing.body)["error"]["code"],
            "UPLOAD_SESSION_ID_REQUIRED",
        )

        for index in range(100):
            submission_id = f"submission-{index:08d}"
            allowed = await self.middleware.dispatch(
                _request(
                    path=f"/api/v1/passports/{submission_id}/client-submit",
                    session_id=submission_id,
                ),
                _ok,
            )
            self.assertEqual(allowed.status_code, 200, index)

    async def test_one_hundred_initial_uploads_behind_one_nat_are_allowed(self) -> None:
        for index in range(100):
            response = await self.middleware.dispatch(
                _request(
                    path="/api/v1/passports/upload/secret-upload-token",
                    session_id=f"attempt-{index:08d}",
                ),
                _ok,
            )
            self.assertEqual(response.status_code, 200, index)

    async def test_one_hundred_bootstrap_flows_share_one_nat(
        self,
    ) -> None:
        missing = await self.middleware.dispatch(
            _request(
                path="/api/v1/upload-links/token/secret-upload-token",
                method="GET",
            ),
            _ok,
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(
            json.loads(missing.body)["error"]["code"],
            "UPLOAD_SESSION_ID_REQUIRED",
        )

        for index in range(100):
            session_id = f"bootstrap-{index:08d}"
            group_response = await self.middleware.dispatch(
                _request(
                    path="/api/v1/upload-links/token/secret-upload-token",
                    method="GET",
                    session_id=session_id,
                ),
                _ok,
            )
            selection_response = await self.middleware.dispatch(
                _request(
                    path=(
                        "/api/v1/upload-links/token/secret-upload-token/"
                        "qualifier-selection"
                    ),
                    method="POST",
                    session_id=session_id,
                ),
                _ok,
            )
            telemetry_response = await self.middleware.dispatch(
                _request(
                    path=(
                        "/api/v1/upload-links/token/secret-upload-token/"
                        "telemetry"
                    ),
                    method="POST",
                    session_id=session_id,
                ),
                _ok,
            )
            self.assertEqual(group_response.status_code, 200, index)
            self.assertEqual(selection_response.status_code, 200, index)
            self.assertEqual(telemetry_response.status_code, 200, index)

    async def test_aggregate_guard_still_caps_rotating_sessions(self) -> None:
        for index in range(180):
            response = await self.middleware.dispatch(
                _request(
                    path="/api/v1/passports/upload/secret-upload-token",
                    session_id=f"attempt-{index:08d}",
                ),
                _ok,
            )
            self.assertEqual(response.status_code, 200, index)

        rejected = await self.middleware.dispatch(
            _request(
                path="/api/v1/passports/upload/secret-upload-token",
                session_id="attempt-99999999",
            ),
            _ok,
        )
        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(
            json.loads(rejected.body)["error"]["code"],
            "UPLOAD_AGGREGATE_RATE_LIMITED",
        )
        self.assertIn("Retry-After", rejected.headers)

    async def test_one_session_cannot_consume_the_shared_nat_budget(self) -> None:
        for _ in range(6):
            response = await self.middleware.dispatch(
                _request(
                    path="/api/v1/passports/upload/secret-upload-token",
                    session_id="same-attempt-1234",
                ),
                _ok,
            )
            self.assertEqual(response.status_code, 200)

        rejected = await self.middleware.dispatch(
            _request(
                path="/api/v1/passports/upload/secret-upload-token",
                session_id="same-attempt-1234",
            ),
            _ok,
        )
        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(
            json.loads(rejected.body)["error"]["code"],
            "UPLOAD_SESSION_RATE_LIMITED",
        )

    async def test_x_forwarded_for_is_ignored_and_counter_keys_are_opaque(self) -> None:
        raw_ip = "203.0.113.25"
        raw_session = "attempt-private-1234"
        raw_token = "secret-upload-token"
        for spoofed_ip in ("1.1.1.1", "8.8.8.8"):
            response = await self.middleware.dispatch(
                _request(
                    path=f"/api/v1/passports/upload/{raw_token}",
                    session_id=raw_session,
                    real_ip=raw_ip,
                    forwarded_for=spoofed_ip,
                ),
                _ok,
            )
            self.assertEqual(response.status_code, 200)

        self.assertEqual(sorted(self.redis.counts.values()), [2, 2])
        for key in self.redis.counts:
            self.assertNotIn(raw_ip, key)
            self.assertNotIn(raw_session, key)
            self.assertNotIn(raw_token, key)
            self.assertNotIn("1.1.1.1", key)
            self.assertNotIn("8.8.8.8", key)

    async def test_initial_upload_requires_a_valid_session_header(self) -> None:
        response = await self.middleware.dispatch(
            _request(path="/api/v1/passports/upload/secret-upload-token"),
            _ok,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.body)["error"]["code"],
            "UPLOAD_SESSION_ID_REQUIRED",
        )
        self.assertEqual(self.redis.counts, {})

    async def test_reconciliation_put_uses_the_bound_initial_upload_budget(
        self,
    ) -> None:
        path = "/api/v1/passports/upload/secret-upload-token"
        missing = await self.middleware.dispatch(
            _request(path=path, method="PUT"),
            _ok,
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(
            json.loads(missing.body)["error"]["code"],
            "UPLOAD_SESSION_ID_REQUIRED",
        )

        allowed = await self.middleware.dispatch(
            _request(
                path=path,
                method="PUT",
                session_id="attempt-reconcile-12345678",
            ),
            _ok,
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(
            allowed.headers["X-RateLimit-Policy"],
            "public-upload-session",
        )

    async def test_followup_requires_separate_upload_credential(self) -> None:
        path = (
            "/api/v1/passports/upload/secret-upload-token/"
            "submission-12345678/image/front"
        )
        missing_response = await self.middleware.dispatch(
            _request(path=path, method="GET"),
            _ok,
        )
        self.assertEqual(missing_response.status_code, 400)
        self.assertEqual(
            json.loads(missing_response.body)["error"]["code"],
            "UPLOAD_SESSION_ID_REQUIRED",
        )

        credential_response = await self.middleware.dispatch(
            _request(
                path=path,
                method="GET",
                session_id="independent-upload-credential-1234",
            ),
            _ok,
        )
        self.assertEqual(credential_response.status_code, 200)
        self.assertEqual(
            credential_response.headers["X-RateLimit-Policy"],
            "public-upload-followup-session",
        )

    async def test_public_upload_fails_closed_when_redis_is_unavailable(self) -> None:
        middleware = RateLimitMiddleware(
            _ok,
            settings=self.settings,
            redis_client=_FakeRedis(fail=True),
            initialize_redis=False,
        )
        response = await middleware.dispatch(
            _request(
                path="/api/v1/passports/upload/secret-upload-token",
                session_id="attempt-redis-failure",
                origin="https://tech.gctravels.com",
            ),
            _ok,
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.body)["error"]["code"],
            "RATE_LIMIT_SERVICE_UNAVAILABLE",
        )
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            "https://tech.gctravels.com",
        )
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_unapproved_origin_is_not_reflected_on_error(self) -> None:
        response = await self.middleware.dispatch(
            _request(
                path="/api/v1/passports/upload/secret-upload-token",
                origin="https://attacker.example",
            ),
            _ok,
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    async def test_authenticated_dashboard_limit_is_per_verified_account(self) -> None:
        self.settings.dashboard_rate_limit_per_minute = 2
        first_user = "11111111-1111-4111-8111-111111111111"
        second_user = "22222222-2222-4222-8222-222222222222"

        def decode(token: str) -> dict[str, str]:
            return {"sub": first_user if token == "first" else second_user}

        with patch(
            "app.presentation.middleware.rate_limit.decode_access_token",
            side_effect=decode,
        ):
            for _ in range(2):
                response = await self.middleware.dispatch(
                    _request(
                        path="/api/v1/dashboard/stats",
                        method="GET",
                        access_token="first",
                    ),
                    _ok,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.headers["X-RateLimit-Policy"],
                    "dashboard-user",
                )

            rejected = await self.middleware.dispatch(
                _request(
                    path="/api/v1/dashboard/stats",
                    method="GET",
                    access_token="first",
                ),
                _ok,
            )
            other_user = await self.middleware.dispatch(
                _request(
                    path="/api/v1/dashboard/stats",
                    method="GET",
                    access_token="second",
                ),
                _ok,
            )

        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(
            json.loads(rejected.body)["error"]["code"],
            "DASHBOARD_RATE_LIMITED",
        )
        self.assertEqual(other_user.status_code, 200)

    async def test_twenty_verified_accounts_on_one_ip_have_independent_bursts(
        self,
    ) -> None:
        self.settings.dashboard_rate_limit_per_minute = 5_000
        self.settings.dashboard_rate_limit_per_second = 1
        self.settings.dashboard_rate_limit_burst = 2

        def decode(token: str) -> dict[str, str]:
            account_number = int(token.removeprefix("account-")) + 1
            return {
                "sub": f"{account_number:08d}-1111-4111-8111-111111111111"
            }

        with patch(
            "app.presentation.middleware.rate_limit.decode_access_token",
            side_effect=decode,
        ):
            for account_number in range(20):
                for _ in range(2):
                    response = await self.middleware.dispatch(
                        _request(
                            path="/api/v1/passports/groups/example/submissions-view",
                            method="GET",
                            access_token=f"account-{account_number}",
                            use_cookie=True,
                            real_ip="203.0.113.50",
                        ),
                        _ok,
                    )
                    self.assertEqual(response.status_code, 200)

            rejected = await self.middleware.dispatch(
                _request(
                    path="/api/v1/dashboard/stats",
                    method="GET",
                    access_token="account-0",
                    use_cookie=True,
                    real_ip="203.0.113.50",
                ),
                _ok,
            )
            another_account = await self.middleware.dispatch(
                _request(
                    path="/api/v1/dashboard/stats",
                    method="GET",
                    access_token="account-20",
                    use_cookie=True,
                    real_ip="203.0.113.50",
                ),
                _ok,
            )

        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(
            json.loads(rejected.body)["error"]["code"],
            "DASHBOARD_RATE_LIMITED",
        )
        self.assertEqual(another_account.status_code, 200)

    async def test_document_images_use_an_independent_authenticated_budget(self) -> None:
        self.settings.dashboard_rate_limit_per_minute = 1
        self.settings.dashboard_media_rate_limit_per_minute = 2
        user_id = "33333333-3333-4333-8333-333333333333"
        image_path = (
            "/api/v1/passports/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/"
            "images/passport_front"
        )

        with patch(
            "app.presentation.middleware.rate_limit.decode_access_token",
            return_value={"sub": user_id},
        ):
            dashboard = await self.middleware.dispatch(
                _request(
                    path="/api/v1/passports/groups/example/submissions-view",
                    method="GET",
                    access_token="valid",
                    use_cookie=True,
                ),
                _ok,
            )
            first_image = await self.middleware.dispatch(
                _request(
                    path=image_path,
                    method="GET",
                    access_token="valid",
                    use_cookie=True,
                ),
                _ok,
            )
            second_image = await self.middleware.dispatch(
                _request(
                    path=image_path,
                    method="GET",
                    access_token="valid",
                    use_cookie=True,
                ),
                _ok,
            )
            dashboard_rejected = await self.middleware.dispatch(
                _request(
                    path="/api/v1/passports/groups/example/submissions-view",
                    method="GET",
                    access_token="valid",
                    use_cookie=True,
                ),
                _ok,
            )

        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(first_image.status_code, 200)
        self.assertEqual(second_image.status_code, 200)
        self.assertEqual(
            first_image.headers["X-RateLimit-Policy"],
            "dashboard-media",
        )
        self.assertEqual(dashboard_rejected.status_code, 429)

    async def test_document_thumbnail_uses_media_budget_and_burst_headers(self) -> None:
        user_id = "44444444-4444-4444-8444-444444444444"
        image_path = (
            "/api/v1/passports/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/"
            "images/visa_photo/thumbnail"
        )

        with patch(
            "app.presentation.middleware.rate_limit.decode_access_token",
            return_value={"sub": user_id},
        ):
            response = await self.middleware.dispatch(
                _request(
                    path=image_path,
                    method="GET",
                    access_token="valid",
                    use_cookie=True,
                ),
                _ok,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-RateLimit-Policy"], "dashboard-media")
        self.assertEqual(response.headers["X-RateLimit-Burst-Capacity"], "60")
        self.assertEqual(response.headers["X-RateLimit-Burst-Remaining"], "59")

    async def test_invalid_access_token_uses_untrusted_ip_fallback(self) -> None:
        with patch(
            "app.presentation.middleware.rate_limit.decode_access_token",
            side_effect=AuthenticationError("invalid"),
        ):
            response = await self.middleware.dispatch(
                _request(
                    path="/api/v1/dashboard/stats",
                    method="GET",
                    access_token="invalid",
                ),
                _ok,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-RateLimit-Policy"], "api")


class PublicUploadProxyContractTests(unittest.TestCase):
    def test_gc_common_document_router_and_edge_pattern_stay_aligned(self) -> None:
        from app.presentation.api.v1.router import api_v1_router

        registered = {
            (route.path, method)
            for route in api_v1_router.routes
            for method in getattr(route, "methods", set())
        }
        self.assertIn(
            ("/gc-app/admin/groups/{group_id}/common-documents", "POST"),
            registered,
        )
        self.assertIn(
            (
                "/gc-app/admin/groups/{group_id}/common-documents/"
                "{document_id}/replace",
                "POST",
            ),
            registered,
        )

        upload_edge = re.compile(
            r"^/api/v1/gc-app/admin/groups/[^/]+/common-documents"
            r"(?:/[^/]+/replace)?/?$"
        )
        self.assertIsNotNone(
            upload_edge.fullmatch(
                "/api/v1/gc-app/admin/groups/group-id/common-documents"
            )
        )
        self.assertIsNotNone(
            upload_edge.fullmatch(
                "/api/v1/gc-app/admin/groups/group-id/common-documents/"
                "document-id/replace"
            )
        )
        for excluded_path in (
            "/api/v1/gc-app/admin/groups/group-id/common-documents/reorder",
            "/api/v1/gc-app/admin/groups/group-id/common-documents/document-id/content",
            "/api/v1/gc-app/admin/groups/group-id/common-documents/document-id/publish",
            "/api/v1/passports/upload/public-token",
        ):
            self.assertIsNone(upload_edge.fullmatch(excluded_path))

    def test_nginx_and_browser_client_keep_the_two_tier_contract(self) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        nginx_main = (repo_root / "nginx" / "nginx.conf").read_text(encoding="utf-8")
        nginx_site = (repo_root / "nginx" / "conf.d" / "default.conf").read_text(
            encoding="utf-8"
        )
        upload_api = (
            repo_root / "frontend" / "features" / "upload" / "api" / "upload.api.ts"
        ).read_text(encoding="utf-8")

        self.assertIn("OPTIONS \"\";", nginx_main)
        self.assertIn("zone=upload_session:10m rate=6r/m", nginx_main)
        self.assertIn(
            "zone=upload_bootstrap_session:10m rate=30r/m",
            nginx_main,
        )
        self.assertIn(
            "zone=upload_bootstrap_aggregate:10m rate=600r/m",
            nginx_main,
        )
        self.assertIn("zone=upload_aggregate:10m rate=120r/m", nginx_main)
        self.assertIn("zone=upload_followup_aggregate:10m rate=100r/s", nginx_main)
        self.assertIn("worker_connections 4096", nginx_main)
        self.assertIn("zone=dashboard_api:10m rate=300r/s", nginx_main)
        self.assertIn("zone=dashboard_media:10m rate=500r/s", nginx_main)
        self.assertIn("keepalive 128", nginx_main)
        self.assertIn("client_submit_id", nginx_main)
        self.assertIn("limit_req_status=$limit_req_status", nginx_main)
        self.assertIn("upstream_status=$upstream_status", nginx_main)
        self.assertIn("return 308 https://$host$request_uri", nginx_site)
        self.assertIn(
            'Strict-Transport-Security "max-age=31536000"',
            nginx_site,
        )
        self.assertIn("limit_req_status 429", nginx_site)
        self.assertIn("limit_req_log_level notice", nginx_site)
        self.assertNotIn("limit_req_log_level warn", nginx_site)
        self.assertIn("error_log /dev/null crit", nginx_site)
        self.assertEqual(nginx_site.count("client_max_body_size 512M"), 1)
        self.assertEqual(nginx_site.count("client_max_body_size 72M"), 1)
        self.assertEqual(nginx_site.count("client_max_body_size 26M"), 1)
        self.assertIn("client_max_body_size 16M", nginx_site)
        self.assertIn("client_max_body_size 64K", nginx_site)
        self.assertGreaterEqual(
            nginx_site.count("client_max_body_size 128K"),
            2,
        )
        self.assertIn("client_max_body_size 35M", nginx_site)
        self.assertIn(
            "passports/groups/[^/]+/import-passports/(?:preview|save)",
            nginx_site,
        )
        self.assertIn(
            "document-distribution/groups/[^/]+/[^/]+/(?:verify|upload|passengers/[^/]+/reupload)",
            nginx_site,
        )
        self.assertIn("document-rename/batches", nginx_site)
        self.assertIn("limit_req zone=upload_aggregate burst=100 nodelay", nginx_site)
        self.assertIn(
            "limit_req zone=upload_followup_aggregate burst=200 nodelay",
            nginx_site,
        )
        self.assertIn("PROXY_UPLOAD_RATE_LIMITED", nginx_site)
        self.assertIn("PROXY_UPLOAD_BOOTSTRAP_RATE_LIMITED", nginx_site)
        self.assertIn("PROXY_UPLOAD_FOLLOWUP_RATE_LIMITED", nginx_site)
        self.assertIn(
            "location ~ ^/api/v1/passports/[^/]+/client-submit/?$",
            nginx_site,
        )
        self.assertIn(
            "location ~ ^/api/v1/upload-links/token/[^/]+",
            nginx_site,
        )
        self.assertIn(
            "images/(?:visa_photo|passport_front|passport_back)(?:/(?:original|thumbnail))?",
            nginx_site,
        )
        self.assertIn(
            "limit_req zone=dashboard_media burst=1000 delay=250",
            nginx_site,
        )
        self.assertIn("limit_req zone=dashboard_api burst=600 delay=150", nginx_site)
        gc_upload_location = (
            "location ~ ^/api/v1/gc-app/admin/groups/[^/]+/common-documents"
            "(?:/[^/]+/replace)?/?$"
        )
        self.assertIn(gc_upload_location, nginx_site)
        self.assertLess(
            nginx_site.index(gc_upload_location),
            nginx_site.index("gc-app(?:/|$)"),
        )
        gc_upload_block = nginx_site[
            nginx_site.index(gc_upload_location) : nginx_site.index(
                "# Verified dashboard traffic",
                nginx_site.index(gc_upload_location),
            )
        ]
        self.assertIn("client_max_body_size 26M", gc_upload_block)
        self.assertIn("client_body_timeout 120s", gc_upload_block)
        self.assertIn("proxy_request_buffering on", gc_upload_block)
        self.assertIn("proxy_read_timeout 120s", gc_upload_block)
        self.assertIn("proxy_send_timeout 120s", gc_upload_block)
        self.assertIn(
            "limit_req zone=dashboard_api burst=600 delay=150",
            gc_upload_block,
        )
        self.assertIn("gc-app(?:/|$)", nginx_site)
        self.assertIn("upload-links(?:$|/(?!token(?:/|$)))", nginx_site)
        self.assertIn(
            "passports(?:$|/(?!upload(?:/|$)|[^/]+/client-submit/?$))",
            nginx_site,
        )
        self.assertIn("whatsapp(?:$|/(?!webhook/?$))", nginx_site)
        self.assertNotIn("limit_req zone=upload burst=5", nginx_site)

        self.assertIn('"X-Upload-Session-ID": sessionId', upload_api)
        self.assertIn("uploadSessionHeaders(uploadIdempotencyKey)", upload_api)
        self.assertGreaterEqual(
            upload_api.count("uploadSessionHeaders(uploadSessionId)"),
            4,
        )

        upload_links_api = (
            repo_root
            / "frontend"
            / "features"
            / "passports"
            / "api"
            / "upload-links.api.ts"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(
            upload_links_api.count("publicUploadHeaders(token)"),
            3,
        )


if __name__ == "__main__":
    unittest.main()
