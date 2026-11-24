"""Mailbox readiness/list views and stable lifecycle route exports."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.email_integrations.overview import email_readiness
from app.application.use_cases.email_integrations.rollout_policy import (
    email_ai_disabled_policy_exists,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import AgencyModel
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes import email_integration_policy_support as _policy_support
from app.presentation.api.v1.schemas.email_integration_schemas import (
    EmailConnectionResponse,
    EmailIntegrationStatusResponse,
)

from . import (
    email_connection_ai_settings,
    email_connection_disconnect,
    email_connection_monitoring,
    email_connection_removal,
)
from .email_connection_ai_settings import (
    update_connection_ai_settings as update_connection_ai_settings,
)
from .email_connection_disconnect import disconnect_email_connection as disconnect_email_connection
from .email_connection_monitoring import pause_connection as pause_connection
from .email_connection_monitoring import resume_connection as resume_connection
from .email_connection_monitoring import sync_connection as sync_connection
from .email_connection_removal import logger as logger
from .email_connection_removal import (
    remove_email_connection_and_data as remove_email_connection_and_data,
)
from .email_integration_access import _current_email_user, _email_owner_filters

router = APIRouter()
_provider_configured = _policy_support._provider_configured
_require_feature = _policy_support._require_feature
_allowed_connection_actions = _policy_support._allowed_connection_actions
_email_removal_confirmation_matches = _policy_support._email_removal_confirmation_matches


@router.get("/status", response_model=EmailIntegrationStatusResponse)
async def email_integration_status(
    current_user: User = Depends(_current_email_user),
) -> EmailIntegrationStatusResponse:
    del current_user
    return EmailIntegrationStatusResponse.model_validate(email_readiness(get_settings()))


@router.get("/connections", response_model=list[EmailConnectionResponse])
async def list_email_connections(
    current_user: User = Depends(_current_email_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[EmailConnectionResponse]:
    settings = get_settings()
    result = await session.execute(
        select(
            EmailConnectionModel,
            AgencyModel.name,
            (
                ~email_ai_disabled_policy_exists(
                    agency_id=EmailConnectionModel.agency_id,
                    owner_user_id=EmailConnectionModel.owner_user_id,
                    connection_id=EmailConnectionModel.id,
                )
            ).label("ai_policy_allows"),
        )
        .join(AgencyModel, AgencyModel.id == EmailConnectionModel.agency_id)
        .where(
            *_email_owner_filters(
                EmailConnectionModel.owner_user_id,
                EmailConnectionModel.agency_id,
                current_user,
            )
        )
        .order_by(EmailConnectionModel.created_at.desc())
    )
    return [
        EmailConnectionResponse(
            id=connection.id,
            agency_id=connection.agency_id,
            agency_name=agency_name,
            provider=connection.provider,
            email_address=connection.email_address,
            status=connection.status,
            last_successful_sync_at=connection.last_successful_sync_at,
            last_sync_attempt_at=connection.last_sync_attempt_at,
            last_error_message=connection.last_error_message,
            ai_processing_enabled=connection.ai_processing_enabled,
            ai_effective_enabled=bool(
                connection.ai_processing_enabled
                and settings.email_ai_runtime_ready
                and connection.status in {"active", "failing"}
                and ai_policy_allows
            ),
            allowed_actions=_allowed_connection_actions(connection, settings),
        )
        for connection, agency_name, ai_policy_allows in result.all()
    ]


# Preserve the original registration order and the actual APIRoute objects.
router.routes.extend(email_connection_monitoring.router.routes)
router.routes.extend(email_connection_disconnect.router.routes)
router.routes.extend(email_connection_removal.router.routes)
router.routes.extend(email_connection_ai_settings.router.routes)
