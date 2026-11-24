"""Current session and exact claim grant registration selection."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.application.mobile.authored_notification_audience import AudienceGrant
from app.application.mobile.notification_errors import NotificationWorkflowError
from app.core.config.settings import get_settings
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobilePassengerSessionIdentityModel,
    MobilePushRegistrationModel,
)


async def registrations_for_grants(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    grants: Sequence[AudienceGrant],
    provider_name: str,
    now: datetime,
    target_keys: dict[tuple[str, ...], set[str]] | None = None,
    max_source_rows: int | None = None,
) -> dict[str, list[MobilePushRegistrationModel]]:
    """Each registration must have a current exact original principal/session grant."""
    if not grants:
        return {}
    grants_by_principal: dict[uuid.UUID, list[AudienceGrant]] = {}
    for grant in grants:
        grants_by_principal.setdefault(grant.principal_id, []).append(grant)
    ids = list(grants_by_principal)
    result: dict[str, dict[str, MobilePushRegistrationModel]] = {}
    for start in range(0, len(ids), 250):
        page = ids[start : start + 250]
        binding_exists = (
            select(MobilePassengerSessionIdentityModel.session_id)
            .where(
                MobilePassengerSessionIdentityModel.session_id == MobileDeviceSessionModel.id,
                MobilePassengerSessionIdentityModel.agency_id == agency_id,
                MobilePassengerSessionIdentityModel.passenger_identity_id.in_(page),
            )
            .exists()
        )
        statement = (
            select(MobilePushRegistrationModel, MobileDeviceSessionModel)
            .options(undefer(MobilePushRegistrationModel.token_ciphertext))
            .join(
                MobileDeviceSessionModel,
                and_(
                    MobileDeviceSessionModel.id == MobilePushRegistrationModel.session_id,
                    MobileDeviceSessionModel.agency_id == MobilePushRegistrationModel.agency_id,
                ),
            )
            .where(
                MobilePushRegistrationModel.agency_id == agency_id,
                MobilePushRegistrationModel.provider == provider_name,
                MobilePushRegistrationModel.platform
                == ("ios" if provider_name == "apns" else "android"),
                MobilePushRegistrationModel.environment
                == ("production" if get_settings().is_production else "development"),
                MobilePushRegistrationModel.app_bundle_id == "com.globalconnects.groupcompanion",
                MobilePushRegistrationModel.status == "active",
                MobilePushRegistrationModel.notifications_authorized.is_(True),
                MobileDeviceSessionModel.status == "active",
                MobileDeviceSessionModel.revoked_at.is_(None),
                MobileDeviceSessionModel.expires_at > now,
                or_(
                    and_(MobileDeviceSessionModel.subject_role == "passenger", binding_exists),
                    and_(
                        MobileDeviceSessionModel.subject_role.in_(
                            ("client_manager", "coordinator")
                        ),
                        MobileDeviceSessionModel.user_id.in_(page),
                    ),
                ),
            )
            .order_by(
                MobilePushRegistrationModel.last_registered_at.desc(),
                MobilePushRegistrationModel.id,
            )
            .execution_options(populate_existing=True)
        )
        if max_source_rows is not None:
            statement = statement.limit(max_source_rows + 1)
        rows = (await session.execute(statement)).all()
        if max_source_rows is not None and len(rows) > max_source_rows:
            raise NotificationWorkflowError("invalid", "audience_limit_exceeded")
        bindings = await _session_bindings(session, agency_id, [device.id for _, device in rows])
        for registration, device in rows:
            if provider_name == "apns" and registration.apns_environment not in {
                "development",
                "production",
            }:
                continue
            device_grants = _device_grants(device, bindings.get(device.id, []), grants_by_principal)
            for grant in device_grants:
                # Prefer newest registration per physical installation, across trip switches.
                keys = (
                    target_keys.get(grant.signature(), set())
                    if target_keys is not None
                    else {grant.person_key}
                )
                for key in keys:
                    result.setdefault(key, {}).setdefault(
                        device.device_identifier_hash, registration
                    )
    return {key: list(values.values()) for key, values in result.items()}


async def _session_bindings(
    session: AsyncSession, agency_id: uuid.UUID, ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[MobilePassengerSessionIdentityModel]]:
    result: dict[uuid.UUID, list[MobilePassengerSessionIdentityModel]] = {}
    for start in range(0, len(ids), 250):
        rows = (
            await session.execute(
                select(MobilePassengerSessionIdentityModel)
                .where(
                    MobilePassengerSessionIdentityModel.agency_id == agency_id,
                    MobilePassengerSessionIdentityModel.session_id.in_(ids[start : start + 250]),
                )
                .execution_options(populate_existing=True)
            )
        ).scalars()
        for row in rows:
            result.setdefault(row.session_id, []).append(row)
    return result


def _device_grants(
    device: MobileDeviceSessionModel,
    bindings: list[MobilePassengerSessionIdentityModel],
    grants: dict[uuid.UUID, list[AudienceGrant]],
) -> list[AudienceGrant]:
    if device.subject_role != "passenger":
        return (
            [grant for grant in grants.get(device.user_id, []) if grant.role == device.subject_role]
            if device.user_id
            else []
        )
    return [
        grant
        for binding in bindings
        for grant in grants.get(binding.passenger_identity_id, [])
        if grant.role == "passenger"
        and binding.agency_id == grant.agency_id
        and binding.group_id == grant.group_id
        and binding.gc_group_access_id == grant.access_id
        and binding.identity_claim_generation == grant.claim_generation
    ]
