"""Typed operational policies shared by HTTP and background workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

DuplicateContactPolicy = Literal["block_same_group", "allow", "block_all"]
DefaultGroupStatus = Literal["active", "closed"]

PLATFORM_SETTINGS_KEY = "global"


class PlatformPolicyConfigurationError(ValueError):
    """Raised when persisted policy data cannot be applied safely."""


class PlatformPolicyProvider(Protocol):
    async def load(self) -> PlatformPolicies: ...


@dataclass(frozen=True, slots=True)
class PlatformPolicies:
    platform_name: str = "Global Connects Dashboard"
    require_client_email: bool = False
    require_client_phone: bool = False
    duplicate_contact_policy: DuplicateContactPolicy = "block_same_group"
    default_group_status: DefaultGroupStatus = "active"
    auto_archive_closed_groups_days: int = 90
    passport_data_retention_days: int = 365
    mrz_review_threshold: float = 0.85
    allow_manager_group_creation: bool = True
    audit_log_retention_days: int = 365

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> PlatformPolicies:
        """Overlay persisted values on safe defaults with strict type/range checks."""

        if value is None:
            return cls()
        defaults = cls()
        platform_name = value.get("platform_name", defaults.platform_name)
        if not isinstance(platform_name, str) or not 2 <= len(platform_name.strip()) <= 80:
            raise PlatformPolicyConfigurationError("platform_name is invalid")

        duplicate_policy = value.get(
            "duplicate_contact_policy",
            defaults.duplicate_contact_policy,
        )
        if duplicate_policy not in {"block_same_group", "allow", "block_all"}:
            raise PlatformPolicyConfigurationError("duplicate_contact_policy is invalid")
        group_status = value.get("default_group_status", defaults.default_group_status)
        if group_status not in {"active", "closed"}:
            raise PlatformPolicyConfigurationError("default_group_status is invalid")

        return cls(
            platform_name=platform_name.strip(),
            require_client_email=_strict_bool(
                value,
                "require_client_email",
                defaults.require_client_email,
            ),
            require_client_phone=_strict_bool(
                value,
                "require_client_phone",
                defaults.require_client_phone,
            ),
            duplicate_contact_policy=duplicate_policy,
            default_group_status=group_status,
            auto_archive_closed_groups_days=_bounded_int(
                value,
                "auto_archive_closed_groups_days",
                defaults.auto_archive_closed_groups_days,
                minimum=1,
                maximum=3650,
            ),
            passport_data_retention_days=_bounded_int(
                value,
                "passport_data_retention_days",
                defaults.passport_data_retention_days,
                minimum=1,
                maximum=3650,
            ),
            mrz_review_threshold=_bounded_float(
                value,
                "mrz_review_threshold",
                defaults.mrz_review_threshold,
                minimum=0.0,
                maximum=1.0,
            ),
            allow_manager_group_creation=_strict_bool(
                value,
                "allow_manager_group_creation",
                defaults.allow_manager_group_creation,
            ),
            audit_log_retention_days=_bounded_int(
                value,
                "audit_log_retention_days",
                defaults.audit_log_retention_days,
                minimum=1,
                maximum=3650,
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "platform_name": self.platform_name,
            "require_client_email": self.require_client_email,
            "require_client_phone": self.require_client_phone,
            "duplicate_contact_policy": self.duplicate_contact_policy,
            "default_group_status": self.default_group_status,
            "auto_archive_closed_groups_days": self.auto_archive_closed_groups_days,
            "passport_data_retention_days": self.passport_data_retention_days,
            "mrz_review_threshold": self.mrz_review_threshold,
            "allow_manager_group_creation": self.allow_manager_group_creation,
            "audit_log_retention_days": self.audit_log_retention_days,
        }


def _strict_bool(value: Mapping[str, Any], key: str, default: bool) -> bool:
    candidate = value.get(key, default)
    if not isinstance(candidate, bool):
        raise PlatformPolicyConfigurationError(f"{key} is invalid")
    return candidate


def _bounded_int(
    value: Mapping[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    candidate = value.get(key, default)
    if isinstance(candidate, bool) or not isinstance(candidate, int):
        raise PlatformPolicyConfigurationError(f"{key} is invalid")
    if not minimum <= candidate <= maximum:
        raise PlatformPolicyConfigurationError(f"{key} is outside the supported range")
    return candidate


def _bounded_float(
    value: Mapping[str, Any],
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    candidate = value.get(key, default)
    if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
        raise PlatformPolicyConfigurationError(f"{key} is invalid")
    result = float(candidate)
    if not minimum <= result <= maximum:
        raise PlatformPolicyConfigurationError(f"{key} is outside the supported range")
    return result
