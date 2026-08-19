from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config.settings import MobileSettings
from app.presentation.api.v1.routes.mobile_associations import (
    android_asset_links,
    apple_app_site_association,
)


def _settings(**mobile_values: object) -> object:
    return SimpleNamespace(
        mobile=MobileSettings(_env_file=None, **mobile_values),
    )


@pytest.mark.asyncio
async def test_apple_association_uses_server_enforced_application_identity() -> None:
    response = await apple_app_site_association(
        settings=_settings(app_attest_team_id="ABCDEFGHIJ")  # type: ignore[arg-type]
    )

    payload = json.loads(response.body)
    detail = payload["applinks"]["details"][0]
    assert detail["appIDs"] == ["ABCDEFGHIJ.com.globalconnects.groupcompanion"]
    assert [component["/"] for component in detail["components"]] == [
        "/gc",
        "/gc/*",
    ]
    assert response.media_type == "application/json"
    assert response.headers["cache-control"].startswith("public, max-age=300")


@pytest.mark.asyncio
async def test_android_association_converts_play_integrity_digests() -> None:
    certificate_digest = bytes(range(32))
    encoded = base64.urlsafe_b64encode(certificate_digest).rstrip(b"=").decode("ascii")
    response = await android_asset_links(
        settings=_settings(  # type: ignore[arg-type]
            play_integrity_allowed_certificate_digests_json=json.dumps([encoded])
        )
    )

    payload = json.loads(response.body)
    assert payload == [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "com.globalconnects.groupcompanion",
                "sha256_cert_fingerprints": [
                    ":".join(f"{byte:02X}" for byte in certificate_digest)
                ],
            },
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "mobile_values"),
    [
        (apple_app_site_association, {}),
        (android_asset_links, {}),
    ],
)
async def test_unconfigured_association_fails_closed(
    handler: object,
    mobile_values: dict[str, object],
) -> None:
    with pytest.raises(HTTPException) as caught:
        await handler(settings=_settings(**mobile_values))  # type: ignore[operator]

    assert caught.value.status_code == 503
    assert caught.value.headers == {
        "Cache-Control": "no-store",
        "Retry-After": "300",
    }
