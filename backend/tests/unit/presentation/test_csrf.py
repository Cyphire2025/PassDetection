"""Tests for cookie-only CSRF protection on staff approval."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.presentation.dependencies.csrf import require_cookie_csrf


def _request(*, headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "https",
            "server": ("api.example.com", 443),
            "path": "/api/v1/passports/id/staff-approve",
            "query_string": b"",
            "headers": [
                (key.lower().encode(), value.encode())
                for key, value in headers.items()
            ],
        }
    )


class CookieCsrfTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = patch(
            "app.presentation.dependencies.csrf.get_settings",
            return_value=SimpleNamespace(
                allowed_origins=["https://office.example.com"],
                jwt=SimpleNamespace(access_cookie_name="access_token"),
            ),
        )
        self.addCleanup(patcher.stop)
        patcher.start()

    async def test_bearer_auth_bypasses_cookie_origin_check(self) -> None:
        await require_cookie_csrf(
            _request(
                headers={
                    "Authorization": "Bearer token",
                    "Cookie": "access_token=cookie-token",
                }
            )
        )

    async def test_cookie_auth_requires_exact_trusted_origin(self) -> None:
        await require_cookie_csrf(
            _request(
                headers={
                    "Cookie": "access_token=cookie-token",
                    "Origin": "https://office.example.com",
                }
            )
        )
        with self.assertRaises(HTTPException) as raised:
            await require_cookie_csrf(
                _request(
                    headers={
                        "Cookie": "access_token=cookie-token",
                        "Origin": "https://evil.example",
                    }
                )
            )
        self.assertEqual(raised.exception.status_code, 403)

