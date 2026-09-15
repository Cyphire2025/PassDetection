"""Authenticated native push registration and same-installation token rotation."""

from __future__ import annotations

import hmac
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.security.mobile_jwt import MobileAccessClaims, hash_mobile_lookup
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobilePushRegistrationModel,
)
from app.presentation.api.v1.schemas.mobile_schemas import MobilePushRegistrationRequest

APP_BUNDLE_ID = "com.globalconnects.groupcompanion"


async def register_push_token(
    session: AsyncSession,
    *,
    body: MobilePushRegistrationRequest,
    claims: MobileAccessClaims,
    device_session: MobileDeviceSessionModel,
    now: datetime,
) -> uuid.UUID:
    expected_device_hash = hash_mobile_lookup(body.installation_id, purpose="device-installation")
    if not hmac.compare_digest(expected_device_hash, device_session.device_identifier_hash):
        raise AuthorizationError("Push registration is not available")
    if (body.provider == "fcm" and device_session.platform != "android") or (
        body.provider == "apns" and device_session.platform != "ios"
    ):
        raise AuthorizationError("Push registration is not available")

    token_identity = (
        f"{body.apns_environment}:{body.push_token}" if body.provider == "apns" else body.push_token
    )
    token_hash = hash_mobile_lookup(token_identity, purpose="push-token")
    registration = (
        await session.execute(
            select(MobilePushRegistrationModel)
            .where(
                MobilePushRegistrationModel.provider == body.provider,
                MobilePushRegistrationModel.token_lookup_hash == token_hash,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if registration is not None and registration.session_id != claims.session_id:
        old_session = (
            await session.execute(
                select(MobileDeviceSessionModel).where(
                    MobileDeviceSessionModel.id == registration.session_id
                )
            )
        ).scalar_one_or_none()
        if old_session is None or not hmac.compare_digest(
            old_session.device_identifier_hash, device_session.device_identifier_hash
        ):
            raise AuthorizationError("Push registration is not available")

    ciphertext = mobile_push_fernet().encrypt(body.push_token.encode("utf-8"))
    if registration is None:
        registration = MobilePushRegistrationModel(
            id=uuid.uuid4(),
            agency_id=claims.agency_id,
            session_id=claims.session_id,
            provider=body.provider,
            platform=device_session.platform,
            environment="production" if get_settings().is_production else "development",
            apns_environment=body.apns_environment,
            app_bundle_id=APP_BUNDLE_ID,
            token_ciphertext=ciphertext,
            token_lookup_hash=token_hash,
            token_key_version=1,
            status="active",
            notifications_authorized=True,
            last_registered_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(registration)
    else:
        registration.agency_id = claims.agency_id
        registration.session_id = claims.session_id
        registration.platform = device_session.platform
        registration.environment = "production" if get_settings().is_production else "development"
        registration.apns_environment = body.apns_environment
        registration.app_bundle_id = APP_BUNDLE_ID
        registration.token_ciphertext = ciphertext
        registration.token_key_version = 1
        registration.status = "active"
        registration.notifications_authorized = True
        registration.last_registered_at = now
        registration.last_failure_at = None
        registration.last_failure_code = None
        registration.revoked_at = None
        registration.updated_at = now

    previous_rows = list(
        (
            await session.execute(
                select(MobilePushRegistrationModel).where(
                    MobilePushRegistrationModel.session_id == claims.session_id,
                    MobilePushRegistrationModel.agency_id == claims.agency_id,
                    MobilePushRegistrationModel.provider.in_(
                        (body.provider, "expo")
                        if body.provider in {"fcm", "apns"}
                        else (body.provider,)
                    ),
                    MobilePushRegistrationModel.id != registration.id,
                    MobilePushRegistrationModel.status == "active",
                )
            )
        ).scalars()
    )
    for previous in previous_rows:
        previous.status = "revoked"
        previous.notifications_authorized = False
        previous.revoked_at = now
        previous.updated_at = now
    await session.flush()
    return registration.id
