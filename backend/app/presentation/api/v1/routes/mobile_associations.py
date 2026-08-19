"""Public mobile verified-link association documents.

The documents contain public signing identities only.  They deliberately reuse
the production App Attest and Play Integrity allowlists so a release cannot
silently publish a different application identity from the one enforced by the
API.
"""

from __future__ import annotations

import base64
import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.config.settings import Settings, get_settings

router = APIRouter()

_ASSOCIATION_HEADERS = {
    "Cache-Control": "public, max-age=300, stale-while-revalidate=86400, stale-if-error=86400",
    "X-Content-Type-Options": "nosniff",
}


def _configuration_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Mobile verified-link association is not configured",
        headers={"Cache-Control": "no-store", "Retry-After": "300"},
    )


def _android_certificate_fingerprints(encoded: str | None) -> list[str]:
    if encoded is None:
        raise _configuration_unavailable()
    try:
        parsed: object = json.loads(encoded)
    except json.JSONDecodeError as exc:  # Settings normally rejects this earlier.
        raise _configuration_unavailable() from exc
    if not isinstance(parsed, list) or not parsed:
        raise _configuration_unavailable()

    fingerprints: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            raise _configuration_unavailable()
        try:
            digest = base64.urlsafe_b64decode(item.rstrip("=") + "=")
        except (ValueError, TypeError) as exc:
            raise _configuration_unavailable() from exc
        if len(digest) != 32:
            raise _configuration_unavailable()
        fingerprints.add(":".join(f"{byte:02X}" for byte in digest))
    return sorted(fingerprints)


@router.api_route(
    "/associations/apple",
    methods=["GET", "HEAD"],
    include_in_schema=False,
    response_class=JSONResponse,
)
async def apple_app_site_association(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Return the AASA document for the one production mobile bundle."""

    mobile = settings.mobile
    if mobile.app_attest_team_id is None:
        raise _configuration_unavailable()
    application_id = f"{mobile.app_attest_team_id}.{mobile.app_attest_bundle_id}"
    return JSONResponse(
        content={
            "applinks": {
                "apps": [],
                "details": [
                    {
                        "appIDs": [application_id],
                        "components": [
                            {"/": "/gc", "comment": "Global Connect Travels activation"},
                            {
                                "/": "/gc/*",
                                "comment": "Global Connect Travels activation data",
                            },
                        ],
                    }
                ],
            }
        },
        headers=_ASSOCIATION_HEADERS,
    )


@router.api_route(
    "/associations/android",
    methods=["GET", "HEAD"],
    include_in_schema=False,
    response_class=JSONResponse,
)
async def android_asset_links(
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    """Return assetlinks.json from the server-enforced signing allowlist."""

    mobile = settings.mobile
    fingerprints = _android_certificate_fingerprints(
        mobile.play_integrity_allowed_certificate_digests_json
    )
    return JSONResponse(
        content=[
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": mobile.play_integrity_package_name,
                    "sha256_cert_fingerprints": fingerprints,
                },
            }
        ],
        headers=_ASSOCIATION_HEADERS,
    )


__all__ = ["android_asset_links", "apple_app_site_association", "router"]
