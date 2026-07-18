"""Privacy-safe Gemini runtime identity for logs and readiness checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from urllib.parse import urlsplit, urlunsplit

from app.core.config.settings import Settings

UNCONFIGURED_PROJECT_ALIASES = {"", "unset", "unconfigured", "unknown"}


@dataclass(frozen=True)
class GeminiRuntimeIdentity:
    project_alias: str
    primary_model: str
    fallback_model: str
    api_endpoint: str
    config_version: str
    api_key_configured: bool

    @property
    def project_alias_configured(self) -> bool:
        return (
            self.project_alias.strip().casefold()
            not in UNCONFIGURED_PROJECT_ALIASES
        )

    def to_safe_dict(self) -> dict[str, str | bool]:
        return asdict(self)


def gemini_runtime_identity(settings: Settings) -> GeminiRuntimeIdentity:
    api_key = settings.google_api_key
    return GeminiRuntimeIdentity(
        project_alias=settings.gemini_project_alias.strip(),
        primary_model=settings.gemini_model.strip(),
        fallback_model=settings.gemini_fallback_model.strip(),
        api_endpoint=_sanitized_endpoint(settings.gemini_api_base_url),
        config_version=settings.gemini_config_version.strip(),
        api_key_configured=bool(
            api_key is not None and api_key.get_secret_value().strip()
        ),
    )


def gemini_configuration_readiness(
    settings: Settings,
) -> tuple[dict[str, str], bool]:
    """Return non-secret production gates and their combined readiness.

    Interactive passport extraction always uses Gemini. Disabling the optional
    post-submission verification stage therefore must not bypass provider
    credentials, runtime identity, or calibrated-capacity checks.
    """

    production = settings.app_env == "production"
    verification_required = settings.gemini_verification_enabled
    identity = gemini_runtime_identity(settings)
    capacity_ready = (
        not production
        or settings.gemini_priority_capacity_calibrated
    )
    identity_ready = (
        not production
        or identity.project_alias_configured
    )
    credentials_ready = (
        not production
        or identity.api_key_configured
    )

    capacity_status = (
        "calibrated_or_non_production"
        if capacity_ready
        else "calibration_required"
    )
    identity_status = (
        "configured_or_non_production"
        if identity_ready
        else "project_alias_required"
    )
    credential_status = (
        "configured_or_non_production"
        if credentials_ready
        else "api_key_required"
    )

    return (
        {
            "gemini_verification": (
                "enabled" if verification_required else "disabled"
            ),
            "gemini_api_credentials": credential_status,
            "gemini_priority_capacity": capacity_status,
            "gemini_runtime_identity": identity_status,
        },
        capacity_ready and identity_ready and credentials_ready,
    )


def _sanitized_endpoint(value: str) -> str:
    """Remove credentials, query parameters, and fragments before logging."""

    parsed = urlsplit(value.strip())
    hostname = parsed.hostname or ""
    if not hostname:
        return "invalid"
    try:
        parsed_port = parsed.port
    except ValueError:
        return "invalid"
    port = f":{parsed_port}" if parsed_port is not None else ""
    netloc = f"{hostname}{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, netloc, path, "", ""))
