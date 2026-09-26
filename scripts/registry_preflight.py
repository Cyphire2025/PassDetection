"""Authenticated GHCR manifest existence check using Docker's configured login.

Only the reviewed GHCR HTTPS endpoints are used. Credentials and tokens remain
in memory, are never command arguments, and never appear in failure messages.
An authorization failure is not evidence that an image or tag is absent.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REGISTRY = "ghcr.io"
MAX_RESPONSE_BYTES = 64 * 1024
MANIFEST_ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)


def docker_credentials() -> tuple[str, str]:
    """Use Docker's documented helper precedence and stdin/stdout protocol."""
    try:
        directory = Path(os.environ.get("DOCKER_CONFIG", str(Path.home() / ".docker")))
        config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        helper = config.get("credHelpers", {}).get(REGISTRY) or config.get("credsStore")
        if helper:
            if not isinstance(helper, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]+", helper
            ):
                raise ValueError
            result = subprocess.run(
                [f"docker-credential-{helper}", "get"],
                input=REGISTRY + "\n",
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if result.returncode or len(result.stdout) > MAX_RESPONSE_BYTES:
                raise ValueError
            credential = json.loads(result.stdout)
            username, secret = credential["Username"], credential["Secret"]
        else:
            credential = config.get("auths", {}).get(REGISTRY, {})
            username, secret = (
                base64.b64decode(credential["auth"], validate=True)
                .decode("utf-8")
                .split(":", 1)
            )
        if (
            not isinstance(username, str)
            or not isinstance(secret, str)
            or not username
            or not secret
            or username == "<token>"
            or ":" in username
            or any(character in username + secret for character in "\r\n")
        ):
            raise ValueError
        return username, secret
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        subprocess.SubprocessError,
    ):
        # Do not include helper stderr, config contents, decoded values or URLs.
        raise ValueError(
            "A valid Docker username/token login for ghcr.io is required"
        ) from None


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        # In particular, never forward Basic/Bearer headers through a redirect.
        return None


def _request(
    method: str, url: str, headers: dict[str, str]
) -> tuple[int, dict[str, str], bytes]:
    opener = urllib.request.build_opener(_NoRedirects())
    request = urllib.request.Request(url, method=method, headers=headers)
    try:
        try:
            response = opener.open(request, timeout=15)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError("Registry preflight response exceeded its size bound")
            return (
                response.code,
                {key.lower(): value for key, value in response.headers.items()},
                body,
            )
    except (OSError, urllib.error.URLError):
        raise ValueError(
            "Registry preflight network/TLS request failed; publication stopped"
        ) from None


def _token_realm(challenge: str) -> str:
    scheme, separator, parameters = challenge.partition(" ")
    if scheme.lower() != "bearer" or not separator:
        raise ValueError("GHCR did not provide the expected Bearer challenge")
    values = {}
    for item in urllib.request.parse_http_list(parameters):
        match = re.fullmatch(r'([a-zA-Z][a-zA-Z0-9_]*)="([^"\r\n]*)"', item.strip())
        if match is None or match[1].lower() in values:
            raise ValueError("GHCR supplied an ambiguous authentication challenge")
        values[match[1].lower()] = match[2]
    if (
        values.get("realm") != "https://ghcr.io/token"
        or values.get("service") != REGISTRY
    ):
        raise ValueError(
            "GHCR authentication challenge points outside the reviewed endpoint"
        )
    return values["realm"]


def registry_tag_exists(reference: str) -> bool:
    """Distinguish an authenticated registry 404 from denied/unknown outcomes.

    Request pull,push scope because this is a publication preflight, including
    first publication. A successful token exchange alone proves no access:
    the registry must authorize the subsequent HEAD before absence is accepted.
    """
    match = re.fullmatch(
        r"ghcr\.io/([a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*):([0-9a-f]{40})",
        reference,
    )
    if match is None:
        raise ValueError(
            "Publication preflight requires a reviewed GHCR image and full revision tag"
        )
    repository, revision = match.groups()
    username, secret = docker_credentials()
    status, headers, _ = _request("GET", "https://ghcr.io/v2/", {})
    if status != 401:
        raise ValueError("Cannot establish the registry authentication challenge")
    realm = _token_realm(headers.get("www-authenticate", ""))
    query = urllib.parse.urlencode(
        {
            "service": REGISTRY,
            "scope": f"repository:{repository}:pull,push",
            "client_id": "passdetection-qualified-release",
        }
    )
    authorization = base64.b64encode(f"{username}:{secret}".encode()).decode("ascii")
    status, _, body = _request(
        "GET", realm + "?" + query, {"Authorization": "Basic " + authorization}
    )
    if status != 200:
        raise ValueError(
            f"Registry token authorization failed (HTTP {status}); publication stopped"
        )
    try:
        payload = json.loads(body)
        token = payload.get("token") or payload.get("access_token")
        if (
            not isinstance(token, str)
            or not token
            or not re.fullmatch(r"[\x21-\x7e]+", token)
            or (
                payload.get("token")
                and payload.get("access_token")
                and payload["token"] != payload["access_token"]
            )
        ):
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValueError(
            "Registry token response is invalid; publication stopped"
        ) from None
    status, headers, _ = _request(
        "HEAD",
        f"https://ghcr.io/v2/{repository}/manifests/{revision}",
        {"Authorization": "Bearer " + token, "Accept": MANIFEST_ACCEPT},
    )
    if headers.get("docker-distribution-api-version") != "registry/2.0":
        raise ValueError(
            "Manifest response is not the expected registry protocol; publication stopped"
        )
    if status == 404:
        return False
    if status == 200 and re.fullmatch(
        r"sha256:[0-9a-f]{64}", headers.get("docker-content-digest", "")
    ):
        return True
    raise ValueError(
        f"Cannot establish destination manifest state (HTTP {status}); publication stopped"
    )
