"""Missing dashboard entry points, reusing canonical first-party read behavior."""

from typing import Literal
from uuid import UUID

from fastapi import Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.presentation.api.v1.routes import (
    companies,
    dashboard,
    whatsapp_catalog,
    whatsapp_groups_read,
)
from app.presentation.api.v1.schemas.company_schemas import (
    CompanyGroupPageResponse,
    CompanyPageResponse,
    CompanySummaryResponse,
)
from app.presentation.api.v1.schemas.dashboard_schemas import DashboardStatsResponse
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppBroadcastGroupResponse


async def assistant_dashboard_summary(current_user: User, session: AsyncSession) -> DashboardStatsResponse:
    return await dashboard.get_dashboard_stats(current_user, dashboard._get_dashboard_use_case(session))


async def assistant_whatsapp_groups(current_user: User, session: AsyncSession, archived: bool = False) -> list[WhatsAppBroadcastGroupResponse]:
    return await whatsapp_groups_read.list_broadcast_groups(current_user, session, archived)


async def assistant_whatsapp_message_topics(current_user: User) -> list[whatsapp_catalog.MessageDefinition]:
    return await whatsapp_catalog.message_catalog(current_user)


async def assistant_companies(
    current_user: User, session: AsyncSession,
    search: str = Query(default="", max_length=120), status: Literal["active", "inactive", "all"] = "all",
    cursor: str | None = Query(default=None, max_length=2048), page_size: int = Query(default=50, ge=1, le=100),
) -> CompanyPageResponse:
    return await companies.list_companies(search=search, status=status, cursor=cursor, page_size=page_size,
        agency_id=current_user.agency_id, user=current_user, session=session, settings=get_settings())


async def assistant_company_summary(company_id: UUID, current_user: User, session: AsyncSession) -> CompanySummaryResponse:
    return await companies.company_summary(company_id, agency_id=current_user.agency_id, user=current_user, session=session)


async def assistant_company_groups(
    company_id: UUID, current_user: User, session: AsyncSession,
    search: str = Query(default="", max_length=120), status: Literal["active", "closed", "archived", "all"] = "all",
    phase: Literal["active", "completed", "all"] = "all", import_only: bool | None = None,
    cursor: str | None = Query(default=None, max_length=2048), page_size: int = Query(default=50, ge=1, le=100),
) -> CompanyGroupPageResponse:
    return await companies.company_groups(company_id=company_id, search=search, status=status,
        import_only=import_only, phase=phase, cursor=cursor, page_size=page_size,
        agency_id=current_user.agency_id, user=current_user, session=session, settings=get_settings())
